"""Persistent, fail-closed execution engine. No live trading path exists."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time

from .strategy import code_valid, execution_reasons, now_iso, number, timestamp, validate_manifest, validate_auto_completion_policy, auto_completion_spread_is_valid, exact_hold_units
from .locking import DataLock

DEFAULT_LIMITS = dict(max_order_notional=1000, max_daily_turnover=5000,
    max_position_notional=2000, max_total_exposure=5000, min_cash_reserve=1000,
    max_daily_loss=200, max_orders_per_day=20, max_quote_age_seconds=60,
    max_spread_bps=50, max_signal_age_seconds=86400)
TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED", "FILLED", "CANCELLED_BEFORE_SEND"}


def _first_execution_sha(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _first_execution_end(record, *, plan, metadata, account_id, clock,
                         execution_delay_minutes, execution_window_seconds):
    """Validate the explicitly authorized original same-session first attempt.

    This does not authorize, renew, change the official opening, or size an order.
    A prior-session record has no effect on the next session's ordinary clock.
    """
    if not isinstance(record, dict) or record.get("signal_date") != metadata.get("signal_date"):
        return None
    from zoneinfo import ZoneInfo
    ny = ZoneInfo("America/New_York")
    opening = timestamp(metadata["next_open_utc"])
    closing, session_close = timestamp(metadata["signal_close_utc"]), timestamp(metadata["next_close_utc"])
    authorized, deadline = timestamp(record["authorized_at_utc"]), timestamp(record["deadline_utc"])
    refs = metadata.get("source_refs")
    if (record.get("reason") != "USER_REQUESTED_SAME_DAY_FIRST_EXECUTION"
            or record.get("signal_date") != metadata.get("signal_date")
            or record.get("signal_date", "") >= record.get("execution_date", "")
            or metadata.get("execution_date") != record["execution_date"]
            or record.get("account_id") != account_id
            or record.get("source_plan_sha256") != _first_execution_sha(plan)
            or not isinstance(refs, dict) or not refs or record.get("source_refs") != refs
            or not isinstance(refs.get("selected/package.json"), dict)
            or refs["selected/package.json"].get("sha256") != record.get("expected_package_sha256")
            or record.get("execution_delay_minutes") != execution_delay_minutes or execution_delay_minutes != 0
            or record.get("execution_window_seconds") != execution_window_seconds or execution_window_seconds != 600
            or any(metadata.get(key) != expected for key, expected in
                   (("execution_delay_minutes", 0), ("execution_window_seconds", 600), ("allow_partial_quotes", True))
                   if key in metadata)
            or any(timestamp(record.get(k)) != instant for k, instant in
                (("next_open_utc", opening), ("signal_close_utc", closing), ("next_close_utc", session_close)))
            or not closing < opening < session_close
            or not opening + timedelta(seconds=600) <= authorized <= clock
            or not authorized < deadline <= min(authorized + timedelta(seconds=600), session_close)
            or any(t.astimezone(ny).date().isoformat() != record["execution_date"]
                   for t in (opening, session_close, authorized, deadline, clock))
            or closing.astimezone(ny).date().isoformat() != record["signal_date"]
            or not isinstance(record.get("authorization_id"), str)
            or not 8 <= len(record["authorization_id"]) <= 80
            or not all(c.isascii() and (c.isalnum() or c in "_-") for c in record["authorization_id"])):
        raise ValueError("FIRST_EXECUTION_BINDING_INVALID")
    return deadline


def _first_continuation_end(continuation, prior, *, plan, metadata, account_id, clock,
                            execution_delay_minutes, execution_window_seconds):
    """Validate one separate explicit residual lease; never replace the first permit."""
    original_end = _first_execution_end(prior, plan=plan, metadata=metadata,
        account_id=account_id, clock=clock, execution_delay_minutes=execution_delay_minutes,
        execution_window_seconds=execution_window_seconds)
    if continuation is None or continuation.get("signal_date") != metadata.get("signal_date"):
        return original_end
    from zoneinfo import ZoneInfo
    authorized, deadline = timestamp(continuation["authorized_at_utc"]), timestamp(continuation["deadline_utc"])
    identity = continuation.get("authorization_id")
    if (original_end is None or continuation.get("reason") != "USER_EXPLICIT_ONCE_SAME_DAY_FIRST_CONTINUATION"
            or continuation.get("prior_permission_sha256") != _first_execution_sha(prior)
            or continuation.get("execution_date") != prior.get("execution_date")
            or continuation.get("account_id") != account_id
            or continuation.get("source_plan_sha256") != _first_execution_sha(plan)
            or not isinstance(identity, str) or not 8 <= len(identity) <= 80
            or not all(x.isascii() and (x.isalnum() or x in "_-") for x in identity)
            or identity == prior.get("authorization_id")
            or not original_end <= authorized <= clock
            or not authorized < deadline <= min(authorized + timedelta(seconds=600), timestamp(metadata["next_close_utc"]))
            or any(x.astimezone(ZoneInfo("America/New_York")).date().isoformat() != prior["execution_date"]
                   for x in (authorized, deadline, clock))):
        raise ValueError("FIRST_CONTINUATION_BINDING_INVALID")
    return deadline


def _validate_first_continuation_state(continuation, state):
    """Keep original phase-specific quantities and processed prefixes immutable."""
    original = continuation.get("execution_snapshot")
    if (not isinstance(original, dict) or continuation.get("execution_sha256") != _first_execution_sha(original)
            or state.get("signal_date") != continuation.get("signal_date")
            or state.get("phase") not in {"SELL", "BUY", "DONE"}):
        raise ValueError("FIRST_CONTINUATION_EXECUTION_CHANGED")
    def phases(value):
        result = {value.get("phase"): value}
        if isinstance(value.get("resume_buy_state"), dict):
            result["BUY"] = value["resume_buy_state"]
        return result
    before, after = phases(original), phases(state)
    for phase, old in before.items():
        if phase not in after:
            if phase == "SELL" and state.get("phase") in {"BUY", "DONE"}:
                continue  # The original SELL -> resumed BUY transition remains authoritative.
            if state.get("phase") == "DONE":
                continue
            raise ValueError("FIRST_CONTINUATION_PHASE_CHANGED")
        current = after[phase]
        if (not set(old.get("processed_codes", [])).issubset(current.get("processed_codes", []))
                or any(current.get("target_quantities", {}).get(code) != qty
                       for code, qty in old.get("target_quantities", {}).items())
                or any(current.get(key) != old.get(key) for key in
                       ("original_target_weights", "original_target_cash_weight") if key in old)):
            raise ValueError("FIRST_CONTINUATION_FIXED_QUANTITY_OR_PROCESSED_CHANGED")
    allowed = set(continuation["allowed_codes"])
    if any(not set(row.get("target_quantities", {})).issubset(allowed) for row in after.values()):
        raise ValueError("FIRST_CONTINUATION_OUTSIDE_ORIGINAL_UNIVERSE")


class Engine:
    def __init__(self, data_dir, broker_factory=None, *, quote_provider=None,
                 paper_account_id="paper", paper_only=False, paper_inception_utc=None):
        if paper_inception_utc is not None:
            if not paper_only:
                raise ValueError("EXPLICIT_INCEPTION_PAPER_ONLY_REQUIRED")
            timestamp(paper_inception_utc)
        self.path = Path(data_dir)
        self.path.mkdir(parents=True, exist_ok=True)
        self.data_lock = DataLock(self.path / "engine.lock")
        self.lock = threading.RLock()
        self.halt_event = threading.Event()
        self.stop_event = threading.Event()
        self.cancel_step = threading.Event()
        self.stop_event.set()
        # CPython #118172: bypass statement-cache races on this shared connection.
        self.db = sqlite3.connect(self.path / "state.sqlite3", check_same_thread=False, cached_statements=0)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          PRAGMA journal_mode=WAL;
          PRAGMA synchronous=FULL;
          CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS strategies(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,created_at TEXT NOT NULL,
            strategy_id TEXT NOT NULL,mode TEXT NOT NULL,account_id TEXT NOT NULL,
            code TEXT NOT NULL,side TEXT NOT NULL,qty INTEGER NOT NULL,limit_price REAL NOT NULL,
            status TEXT NOT NULL,order_id TEXT,order_type TEXT NOT NULL DEFAULT 'NORMAL');
          CREATE TABLE IF NOT EXISTS audit(time TEXT,event TEXT,detail TEXT);
          CREATE TABLE IF NOT EXISTS baselines(day TEXT,account TEXT,equity REAL,PRIMARY KEY(day,account));
          CREATE TABLE IF NOT EXISTS paper_fills(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_batches(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS paper_nav(day TEXT PRIMARY KEY,payload TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS order_fills(id TEXT PRIMARY KEY,payload TEXT NOT NULL);
        """)
        # Existing simulated orders were submitted as limit orders. Preserve
        # their type on upgrade so pending reconciliation never changes it.
        if "order_type" not in {row[1] for row in self.db.execute("PRAGMA table_info(orders)")}:
            self.db.execute("ALTER TABLE orders ADD COLUMN order_type TEXT NOT NULL DEFAULT 'NORMAL'")
            self.db.commit()
        self.mode = "paper"
        self.broker = None
        self.broker_factory = broker_factory
        self.paper_only = bool(paper_only)
        self.quote_provider = quote_provider
        self.automatic_completion_policy_provider = None
        self.paper_account_id = str(paper_account_id)
        if not self.paper_account_id:
            raise ValueError("纸面账户标识不能为空")
        self.account_id = self.paper_account_id
        if self.paper_only:
            identity = self._get("paper_account_identity", self.paper_account_id)
            if identity != self.paper_account_id:
                self.db.close()
                self.data_lock.close()
                raise ValueError("独立纸面账本不能换用另一个账户标识")
            self._set("paper_account_identity", self.paper_account_id)
            from zoneinfo import ZoneInfo
            inception = self._get("paper_inception_utc", None)
            if (inception is not None and paper_inception_utc is not None
                    and timestamp(inception) != timestamp(paper_inception_utc)):
                self.db.close()
                self.data_lock.close()
                raise ValueError("PAPER_BOOK_ACCEPTED_INCEPTION_CHANGED")
            if inception is None:
                inception = paper_inception_utc if paper_inception_utc is not None else now_iso()
                self._set("paper_inception_utc", inception)
                day = timestamp(inception).astimezone(ZoneInfo("America/New_York")).date().isoformat()
                initial = dict(date=day, cash=10000.0, equity=10000.0, nav=1.0, fees=0.0,
                               basis="INITIAL_CASH", asof=inception, sources=[], paper=True)
                self.db.execute("INSERT OR IGNORE INTO paper_nav VALUES (?,?)", (day, json.dumps(initial)))
                self.db.commit()
            self.paper_inception_utc = inception
            self.paper_inception_date = timestamp(inception).astimezone(ZoneInfo("America/New_York")).date().isoformat()
            if self._get("paper_metrics", None) is None:
                self._set("paper_metrics", dict(peak_equity=10000.0, max_drawdown_fraction=0.0,
                                                 last_observed_at=inception))
        else:
            self.paper_inception_utc = self.paper_inception_date = None
        self.connection = {"connected": False, "accounts": [], "port": 18441, "security_firm": "FUTUSECURITIES", "message": "尚未连接 OpenD"}
        self.limits = self._get("limits", DEFAULT_LIMITS.copy())
        self.active = self._get("active", None)
        self.halt_reason = self._get("halt_reason", "")
        if self.halt_reason:
            self.halt_event.set()
        self.preview_result = None
        self.account = {}
        self.last_error = ""
        self.worker = None
        self._audit("BOOT", "已停止启动；实盘能力不存在；Moomoo 模拟账户须重新选择")
        if self._pending():
            self._halt("存在未完成或结果未知的模拟订单，请先连接原模拟账户对账")

    def _get(self, key, default):
        row = self.db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def _set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
        self.db.commit()

    def _audit(self, event, detail):
        self.db.execute("INSERT INTO audit VALUES (?,?,?)", (now_iso(), event, str(detail)[:2000]))
        self.db.commit()

    def _pending(self):
        return [dict(r) for r in self.db.execute("SELECT * FROM orders WHERE mode='moomoo_simulate'") if r["status"] not in TERMINAL]

    def _halt(self, reason):
        self.halt_event.set()
        self.stop_event.set()
        self.halt_reason = reason
        self._set("halt_reason", reason)
        self._audit("HALT", reason)

    def halt(self):
        # Set outside the engine lock, so an in-flight SDK call cannot hide a stop request.
        self.halt_event.set()
        self.stop_event.set()
        self.cancel_step.set()
        with self.lock:
            self._halt("手动紧急停止；已送达券商的订单需在 Moomoo 查询或撤单")

    def stop(self):
        self.stop_event.set()
        self.cancel_step.set()
        with self.lock:
            self._audit("STOP", "停止后续提交；不自动撤销已发送的模拟订单")

    def reset_halt(self):
        with self.lock:
            self._require_stopped()
            if self._pending():
                raise ValueError("未完成/未知订单尚未对账，禁止解除停止")
            self.halt_event.clear()
            self.halt_reason = ""
            self._set("halt_reason", "")
            self._audit("RESET_HALT", "人工解除停止，自动执行仍关闭")

    def _require_stopped(self):
        if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
            raise ValueError("请先暂停自动执行，等待当前轮结束")

    def import_strategy(self, manifest):
        manifest = validate_manifest(manifest)
        with self.lock:
            self._require_stopped()
            if self._pending():
                raise ValueError("请先对账未完成的模拟订单")
            self.db.execute("INSERT OR REPLACE INTO strategies VALUES (?,?)", (manifest["strategy_id"], json.dumps(manifest, ensure_ascii=False)))
            self.db.commit()
            self.preview_result = None
            self._audit("IMPORT", f"{manifest['strategy_id']} / {manifest['revision']}")
            return manifest

    def switch(self, strategy_id):
        with self.lock:
            self._require_stopped()
            if self._pending():
                raise ValueError("存在未完成订单，先对账才能切换策略")
            if not self.db.execute("SELECT id FROM strategies WHERE id=?", (strategy_id,)).fetchone():
                raise ValueError("策略不存在")
            self.active = strategy_id
            self._set("active", strategy_id)
            self.preview_result = None
            self._audit("SWITCH", strategy_id + "；未列出的证券保持原持仓")

    def set_limits(self, changes):
        with self.lock:
            self._require_stopped()
            if not isinstance(changes, dict) or set(changes) - set(DEFAULT_LIMITS):
                raise ValueError("未知风控字段")
            proposed = {**self.limits, **changes}
            for k, v in proposed.items():
                number(v, k, 0 if k == "min_cash_reserve" else 1)
            if type(proposed["max_orders_per_day"]) is not int or proposed["max_orders_per_day"] > 1000:
                raise ValueError("日订单数必须是1至1000整数")
            if proposed["max_quote_age_seconds"] > 120 or proposed["max_signal_age_seconds"] > 86400:
                raise ValueError("行情最长120秒，信号最长24小时")
            if proposed["max_spread_bps"] > 200:
                raise ValueError("价差上限不能超过200基点")
            self.limits = proposed
            self._set("limits", proposed)
            self.preview_result = None
            self._audit("LIMITS", json.dumps(proposed))

    def _factory(self, **kwargs):
        if self.broker_factory:
            return self.broker_factory(**kwargs)
        from .brokers import MoomooBroker
        return MoomooBroker(**kwargs)

    def connect(self, port=18441, security_firm="FUTUSECURITIES"):
        if self.paper_only:
            raise ValueError("此独立账户永远为本地纸面模式，不连接交易账户")
        with self.lock:
            self._require_stopped()
            if self.mode != "paper":
                raise ValueError("已选定模拟账户；请先切回纸面模式后更改 OpenD 连接")
            if type(port) is not int or not 1 <= port <= 65535:
                raise ValueError("端口无效")
            candidate = self._factory(port=port, security_firm=security_firm)
            try:
                info = candidate.probe()
            finally:
                candidate.close()
            self.connection = {**info, "connected": True, "port": port, "security_firm": security_firm}
            self._audit("CONNECT_READ_ONLY", "只读发现模拟账户；没有查询实盘资金或解锁")
            return self.connection

    def set_mode(self, mode, account_id=None, confirmation=None):
        if self.paper_only:
            raise ValueError("此独立账户永远为本地纸面模式，不允许切换交易模式")
        with self.lock:
            self._require_stopped()
            if mode not in ("paper", "moomoo_simulate"):
                raise ValueError("实盘模式未实现，禁止启用")
            pending = self._pending()
            if pending and (mode != "moomoo_simulate" or any(r["account_id"] != str(account_id) for r in pending)):
                raise ValueError("须选择存在未完成订单的原模拟账户进行对账")
            if mode == "moomoo_simulate":
                if confirmation != "SIMULATE" or not account_id or not self.connection["connected"]:
                    raise ValueError("先只读连接，再显式选择模拟账户并确认 SIMULATE")
                ids = {str(a["account_id"]) for a in self.connection.get("accounts", [])}
                if str(account_id) not in ids:
                    raise ValueError("模拟账户不在已发现的账户列表中")
                candidate = self._factory(port=self.connection["port"], security_firm=self.connection["security_firm"], account_id=str(account_id))
                try:
                    candidate.probe()
                except Exception:
                    candidate.close()
                    raise
                candidate.cancel_check = lambda: self.halt_event.is_set() or self.cancel_step.is_set()
            else:
                candidate = None
                account_id = "paper"
            if self.broker:
                self.broker.close()
            self.broker, self.mode, self.account_id = candidate, mode, str(account_id)
            self.preview_result, self.account = None, {}
            self._audit("MODE", f"{mode}；实盘禁用")

    def demo(self):
        with self.lock:
            self._require_stopped()
            if self.mode != "paper":
                raise ValueError("请切回本地纸面模式后创建演示")
            now = datetime.now(timezone.utc)
            manifest = dict(schema_version=1, strategy_id="demo-balanced", name="离线演示 · 双标的目标持仓", revision="1",
                asof=now.isoformat(), expires_at=(now + timedelta(hours=1)).isoformat(), provenance="demo",
                targets=[dict(code="US.AAPL", target_qty=2), dict(code="US.MSFT", target_qty=1)],
                source="内置合成数据；不是行情、投资建议或策略收益验证")
            self.import_strategy(manifest)
            self.switch(manifest["strategy_id"])
            return manifest

    def _snapshot(self, codes, *, allow_partial_quotes=False):
        if self.mode == "moomoo_simulate":
            if not self.broker:
                raise ValueError("未选择模拟账户")
            if allow_partial_quotes:
                return self.broker.snapshot_partial(codes)
            return self.broker.snapshot(codes)
        ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
        if self.quote_provider is not None:
            requested = sorted(set(codes) | set(ledger["positions"]))
            quotes = self.quote_provider(requested)
            self.paper_mark(quotes)
            book = self.paper_book()
            if book["equity"] is None:
                raise ValueError("真实行情未覆盖全部纸面持仓")
            return dict(cash=book["cash"], equity=book["equity"],
                positions={row["code"]: dict(qty=row["qty"], sellable=row["qty"],
                            market_value=row["market_value"]) for row in book["positions"]},
                quotes=quotes, open_orders=[])
        prices = {"US.AAPL": 200.0, "US.MSFT": 400.0, "US.SPY": 500.0}
        quotes = {code: dict(price=p, bid=p - .01, ask=p + .01, asof=now_iso(), lot_size=1, price_tick=.01, tradable=True) for code, p in prices.items()}
        positions = {code: dict(qty=qty, sellable=qty, market_value=qty * prices[code]) for code, qty in ledger["positions"].items()}
        return dict(cash=ledger["cash"], equity=ledger["cash"] + sum(p["market_value"] for p in positions.values()), positions=positions, quotes=quotes, open_orders=[])

    def paper_book(self):
        """Read the independent local book without a network request or a synthetic mark."""
        with self.lock:
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0})
            marks = self._get("paper_marks", {})
            cash = number(ledger["cash"], "纸面现金")
            rows, values = [], []
            for code, qty in sorted(ledger["positions"].items()):
                if not qty:
                    continue
                mark = marks.get(code, {})
                price = mark.get("price")
                value = qty * price if price is not None else None
                values.append(value)
                rows.append(dict(code=code, ticker=code.removeprefix("US."), qty=qty,
                    market_value=value, mark_price=price, mark_asof=mark.get("asof"),
                    mark_source=mark.get("source"), mark_basis=mark.get("basis")))
            equity = cash + sum(values) if all(v is not None for v in values) else None
            metrics = self._get("paper_metrics", {"peak_equity": 10000.0, "max_drawdown_fraction": 0.0})
            return dict(account_id=self.paper_account_id, mode="paper", initial_cash=10000.0,
                cash=cash, equity=equity, return_fraction=equity / 10000.0 - 1 if equity is not None else None,
                max_drawdown_fraction=metrics["max_drawdown_fraction"],
                fees=ledger.get("fees", 0.0), positions=rows, paper=True,
                trade_count=self.db.execute("SELECT count(*) FROM paper_fills").fetchone()[0],
                inception_utc=self.paper_inception_utc, inception_date=self.paper_inception_date)

    def _observe_paper_equity(self, equity, asof=None):
        """Keep every observed peak/loss independently of replaceable daily NAV rows."""
        if equity is None:
            return
        value = number(equity, "已观测纸面权益")
        metrics = self._get("paper_metrics", dict(peak_equity=10000.0,
                            max_drawdown_fraction=0.0, last_observed_at=None))
        observed = timestamp(asof).isoformat() if asof else None
        last = metrics.get("last_observed_at")
        if observed and last and timestamp(observed) < timestamp(last):
            return  # A verified prior close is historical, not a new loss after today's peak.
        peak = max(number(metrics["peak_equity"], "纸面权益峰值", 1e-12), value)
        drawdown = min(number(metrics["max_drawdown_fraction"], "纸面最大回撤", -1), value / peak - 1)
        self._set("paper_metrics", dict(peak_equity=peak, max_drawdown_fraction=drawdown,
                                        last_observed_at=observed or last))

    def paper_mark(self, quotes, *, day=None, basis="MOOMOO_REALTIME",
                   observed_at_utc=None, failed_quotes=None):
        """Persist observed marks; callers supply real quotes or verified exact-date closes."""
        with self.lock:
            if self.mode != "paper":
                raise ValueError("只允许标记本地纸面账本")
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
            marks = self._get("paper_marks", {})
            observed = timestamp(observed_at_utc) if observed_at_utc is not None else None
            fresh = set()
            failures = dict(failed_quotes or {})
            for code, quote in quotes.items():
                if code not in ledger["positions"] or not ledger["positions"][code]:
                    continue
                price = number(quote["price"], "真实标价", minimum=1e-12)
                asof = timestamp(quote["asof"]).isoformat()
                if observed is not None and (not 0 <= (observed - timestamp(asof)).total_seconds() <= 30
                        or quote.get("tradable") is not True or quote.get("currency") != "USD"
                        or quote.get("market") != "US" or quote.get("source") != "MOOMOO_OPEND"):
                    raise ValueError("持仓估值只接受30秒内正常美股真实报价: " + code)
                old = marks.get(code)
                if old and timestamp(old["asof"]) > timestamp(asof):
                    continue  # A prior close must never overwrite a newer live mark.
                marks[code] = dict(price=price, asof=asof, source=quote.get("source", "UNKNOWN"), basis=basis)
                fresh.add(code)
            self._set("paper_marks", marks)
            book = self.paper_book()
            valuation = None
            if observed is not None:
                held = {row["code"] for row in book["positions"] if row["qty"]}
                valid_marks, unmarked = {}, []
                for code in sorted(held):
                    mark = marks.get(code, {})
                    try:
                        number(mark["price"], "已记录真实标价", minimum=1e-12)
                        if (timestamp(mark["asof"]) > observed or not mark.get("source")
                                or mark["source"] == "UNKNOWN"
                                or mark.get("basis") not in {"MOOMOO_REALTIME", "SIGNAL_CLOSE"}):
                            raise ValueError("持仓旧标价来源或时间不合格")
                        valid_marks[code] = mark
                    except (KeyError, TypeError, ValueError):
                        unmarked.append(code)
                failures = {code: str(failures.get(code, "没有合格的新报价")) for code in sorted(held - fresh)}
                stamps = [mark["asof"] for mark in valid_marks.values()]
                valuation = dict(observed_at_utc=observed.isoformat(), held_count=len(held),
                    fresh_held_count=len(fresh & held), complete_live_coverage=held.issubset(fresh),
                    held_asof_min=min(stamps, key=timestamp, default=None),
                    held_asof_max=max(stamps, key=timestamp, default=None), unmarked_codes=unmarked,
                    failed_quotes=[dict(code=code, reason=reason) for code, reason in failures.items()],
                    nav_recorded=False)
                book["valuation"] = valuation
            can_observe = valuation is None or (valuation["fresh_held_count"] > 0 and not valuation["unmarked_codes"])
            if can_observe:
                self._observe_paper_equity(book["equity"], valuation["held_asof_max"] if valuation is not None
                    else max((q["asof"] for q in marks.values()), default=None))
            book["max_drawdown_fraction"] = self._get("paper_metrics", {"max_drawdown_fraction": 0.0})["max_drawdown_fraction"]
            if day is not None and can_observe and book["equity"] is not None and (
                    self.paper_inception_date is None or day >= self.paper_inception_date):
                payload = dict(date=day, cash=book["cash"], equity=book["equity"],
                    nav=book["equity"] / 10000.0, fees=book["fees"], basis=basis,
                    asof=max((q["asof"] for q in marks.values()), default=None),
                    sources=sorted({q["source"] for q in marks.values()}), paper=True)
                if valuation is not None:
                    valuation["nav_recorded"] = True
                    payload.update(valuation)
                    payload.update(basis="MOOMOO_REALTIME" if valuation["complete_live_coverage"] else "OBSERVED_MIXED_MARKS",
                        asof=valuation["held_asof_min"],
                        sources=sorted({marks[row["code"]]["source"] for row in book["positions"] if row["qty"]}))
                self.db.execute("INSERT OR REPLACE INTO paper_nav VALUES (?,?)", (day, json.dumps(payload)))
                self.db.commit()
            return book

    def paper_record_close(self, day, state):
        """Record a completed session using canonical raw USD closes, never intraday quotes."""
        with self.lock:
            if state.get("signal_date") != day or state.get("valuation_basis") != "SIGNAL_CLOSE":
                raise ValueError("收盘账户状态必须与完成信号日一致")
            if self.paper_inception_date is not None and day < self.paper_inception_date:
                return False
            latest = self.db.execute("SELECT payload FROM paper_fills ORDER BY rowid DESC LIMIT 1").fetchone()
            if latest and json.loads(latest[0])["execution_date"] > day:
                return False  # Today's post-open holdings did not exist at the prior close.
            value = number(state["equity"], "真实收盘权益", minimum=1e-12)
            asof = timestamp(state["close_asof_utc"]).isoformat()
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
            prices = state.get("prices", {})
            if timestamp(asof).date().isoformat() != day or any(c not in prices for c, q in ledger["positions"].items() if q):
                raise ValueError("真实收盘标价日期或持仓覆盖不完整")
            measured = ledger["cash"] + sum(q * number(prices[c], "真实收盘标价", 1e-12)
                                          for c, q in ledger["positions"].items() if q)
            if abs(measured - value) > max(1e-7, value * 1e-9):
                raise ValueError("真实收盘权益与独立账本不一致")
            quotes = {code: dict(price=price, asof=asof, source="CANONICAL_RAW_USD_CLOSE")
                      for code, price in state.get("prices", {}).items()}
            self.paper_mark(quotes, basis="SIGNAL_CLOSE")
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
            payload = dict(date=day, cash=ledger["cash"], equity=value, nav=value / 10000.0,
                fees=ledger.get("fees", 0.0), basis="SIGNAL_CLOSE", asof=asof,
                source_refs=state.get("source_refs", {}), paper=True)
            self.db.execute("INSERT OR REPLACE INTO paper_nav VALUES (?,?)", (day, json.dumps(payload)))
            self.db.commit()
            self._observe_paper_equity(value, asof)
            return True

    def _paper_batch_id(self, strategy_id, signal_date, execution_date):
        identity = [self.paper_account_id, strategy_id, signal_date, execution_date]
        epoch = self._get("paper_epoch_id", None)
        if epoch is not None:
            if not isinstance(epoch, str) or not epoch or len(epoch) > 64 or not all(
                    char.isascii() and (char.isalnum() or char in "_-") for char in epoch):
                raise ValueError("PAPER_RESET_EPOCH_IDENTITY_INVALID")
            identity.extend(["reset", epoch])
        return hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()

    def _store_first_execution_permission(self, key, record):
        """Retain complete immutable per-signal grants in the original settings store."""
        previous = self._get(key, None)
        with self.db:
            for item in ([previous] if previous is not None else []) + [record]:
                slot = key + ":" + item["signal_date"]
                row = self.db.execute("SELECT value FROM settings WHERE key=?", (slot,)).fetchone()
                if row and json.loads(row[0]) != item:
                    raise ValueError("FIRST_EXECUTION_IMMUTABLE_PERMISSION_CHANGED")
                self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (slot,
                    json.dumps(item, ensure_ascii=False, allow_nan=False)))
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key,
                json.dumps(record, ensure_ascii=False, allow_nan=False)))

    def _first_continuation_record(self, key, prior):
        value = self._get(key, None)
        if not isinstance(prior, dict) or not isinstance(value, dict) or value.get("signal_date") != prior.get("signal_date"):
            return None
        if self._get(key + ":" + value["signal_date"], None) != value:
            raise ValueError("FIRST_CONTINUATION_IMMUTABLE_PERMISSION_CHANGED")
        return value

    def _first_execution_deadline(self, key, prior, **kwargs):
        return _first_continuation_end(self._first_continuation_record(key, prior), prior, **kwargs)

    def _paper_first_no_attempt(self, metadata):
        if (self.db.execute("SELECT 1 FROM orders WHERE created_at>=? LIMIT 1", (metadata["next_open_utc"],)).fetchone()
                or any(self.db.execute("SELECT 1 FROM " + table +
                    " WHERE json_extract(payload,'$.execution_date')=? LIMIT 1", (metadata["execution_date"],)).fetchone()
                    for table in ("paper_batches", "paper_fills"))):
            raise ValueError("PAPER_FIRST_EXECUTION_ALREADY_ATTEMPTED")

    def _paper_first_baseline(self):
        return _first_execution_sha({"paper": self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0}),
            "epoch": self._get("paper_epoch_id", None)})

    def _paper_first_execution_end(self, record, *, strategy_id, plan, batch, batch_id,
                                   metadata, clock, execution_window_seconds):
        continuation = self._first_continuation_record("paper_first_continuation", record)
        end = self._first_execution_deadline("paper_first_continuation", record, plan=plan, metadata=metadata, account_id=self.paper_account_id,
            clock=clock, execution_delay_minutes=0, execution_window_seconds=execution_window_seconds)
        if end is None:
            return None
        if (not self.paper_only or self.mode != "paper" or self.broker is not None
                or strategy_id not in {"HGB_DIAG_5", "HGB_FACTOR_5"}
                or self.account_id != self.paper_account_id
                or self._get("paper_account_identity", None) != self.paper_account_id
                or self.halt_event.is_set() or record.get("strategy_id") != strategy_id
                or record.get("batch_id") != batch_id):
            raise ValueError("PAPER_FIRST_EXECUTION_ACCOUNT_INVALID")
        if batch is None:
            if self._paper_first_baseline() != (continuation or record).get("pre_first_ledger_sha256"):
                raise ValueError("PAPER_FIRST_EXECUTION_LEDGER_CHANGED")
            self._paper_first_no_attempt(metadata)
        elif (batch.get("first_execution_permission_sha256") != _first_execution_sha(record)
                or (continuation is not None and batch.get("first_continuation_permission_sha256") != _first_execution_sha(continuation))
                or batch.get("policy") != "QUALIFIED_QUOTES_ONLY"
                or batch.get("status") not in {"WAITING_QUOTES", "PARTIALLY_EXECUTED", "EXECUTED"}
                or batch.get("required_codes") != record.get("initial_required_codes")
                or not set(batch.get("processed_codes", [])).issubset(batch.get("required_codes", []))
                or batch.get("source_plan") != plan
                or batch.get("source_plan_sha256") != record["source_plan_sha256"]
                or batch.get("source_refs") != record["source_refs"]
                or batch.get("batch_id") != batch_id):
            raise ValueError("PAPER_FIRST_EXECUTION_BATCH_CHANGED")
        return end


    def _automatic_completion_policy(self, clock, strategy_id, expected_policy=None, execution_date=None):
        """Validate the canonical Cohort policy and its original-account audit projection."""
        from datetime import datetime as ClockType
        if not isinstance(clock, ClockType) or clock.tzinfo is None or clock.utcoffset() is None:
            raise ValueError("AUTOMATIC_COMPLETION_CLOCK_INVALID")
        provider = self.automatic_completion_policy_provider
        primary = provider() if callable(provider) else None
        if primary is None:
            if expected_policy is not None:
                raise ValueError("AUTOMATIC_COMPLETION_PRIMARY_POLICY_MISSING")
            return None
        validate_auto_completion_policy(primary)
        if expected_policy is not None and primary != expected_policy:
            raise ValueError("AUTOMATIC_COMPLETION_PRIMARY_POLICY_CHANGED")
        from datetime import date
        from zoneinfo import ZoneInfo
        day = execution_date or clock.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        date.fromisoformat(day)
        if not primary["enabled"] or not primary["effective_execution_date"] <= day < primary["evaluation_end_exclusive"]:
            return None
        if strategy_id not in primary["active_strategy_ids"]:
            return None  # A standing grant remains scoped to its original strategies.
        if (timestamp(primary["authorized_at_utc"]) > clock
                or self._get("automatic_completion_policy", None) != primary):
            raise ValueError("AUTOMATIC_COMPLETION_PROJECTION_CHANGED")
        audit = self.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
            ("AUTOMATIC_COMPLETION_POLICY_AUTHORIZED", primary["authorized_at_utc"]))
        digest = _first_execution_sha(primary)
        if not any(_first_execution_sha(json.loads(row[0])) == digest for row in audit):
            raise ValueError("AUTOMATIC_COMPLETION_POLICY_AUDIT_CHANGED")
        if self.paper_only:
            if (self.mode != "paper" or self.broker is not None
                    or self.account_id != self.paper_account_id
                    or self._get("paper_account_identity", None) != self.paper_account_id):
                raise ValueError("AUTOMATIC_COMPLETION_PAPER_ACCOUNT_CHANGED")
        else:
            # Before the original account connects, display/preparation has no automatic authority.
            if self.broker is None and self.mode == "paper":
                return None
            capital = self._get("best_capital", {})
            if (self.mode != "moomoo_simulate" or self.broker is None
                    or self.account_id != primary["broker_account_id"]
                    or str(self.broker.account_id) != self.account_id
                    or self._get("best_account", None) != self.account_id
                    or capital.get("account_id") != self.account_id
                    or capital.get("budget") != primary["broker_budget"]):
                raise ValueError("AUTOMATIC_COMPLETION_BROKER_ACCOUNT_OR_BUDGET_CHANGED")
        return primary

    def _manual_residual_sell_permission(self, manifest, clock, *, completion_only=False, completion_execution_state=None):
        """Check the compact immutable permit on every preview and before submission."""
        try:
            origin = json.loads(manifest.get("source", ""))
        except (TypeError, ValueError):
            origin = {}
        ref = origin.get("manual_residual_sell_permission_sha256") if isinstance(origin, dict) else None
        if ref is None:
            return None
        grant = self._get("best_manual_residual_sell", {})
        saved = self._get("best_plan", {})
        capital = self._get("best_capital", {})
        if completion_execution_state is not None and not completion_only:
            raise ValueError("MANUAL_RESIDUAL_SELL_COMPLETION_STATE_FOR_ACCOUNTING_ONLY")
        state = self._get("best_execution", {}) if completion_execution_state is None else completion_execution_state
        renewal = self._get("best_same_day_catchup_renewal", {})
        slot = self._get("best_manual_residual_sell:" + str(grant.get("signal_date")), None)
        runtime = self._get("best_manual_residual_sell_state:" + str(grant.get("authorization_id")), {})
        from zoneinfo import ZoneInfo
        if (not isinstance(grant, dict) or slot != grant or ref != _first_execution_sha(grant)
                or grant.get("schema_version") != 1
                or grant.get("reason") != "USER_EXPLICIT_ONCE_MANUAL_RESIDUAL_SELL"
                or self.mode != "moomoo_simulate" or self.broker is None
                or self.account_id != grant.get("account_id")
                or self.account_id != self._get("best_account", None)
                or str(self.broker.account_id) != self.account_id
                or grant.get("budget") != capital.get("budget")
                or grant.get("unused_cash") != capital.get("unused_cash")
                or capital.get("account_id") != self.account_id
                or (not completion_only and runtime.get("status") in {"CANCELLED", "COMPLETED"})
                or _first_execution_sha(saved.get("plan")) != grant.get("expected_plan_sha256")
                or _first_execution_sha(state) != grant.get("expected_execution_sha256")
                or _first_execution_sha(renewal) != grant.get("expected_prior_sha256")
                or _first_execution_sha(saved.get("metadata", {}).get("source_refs")) != grant.get("source_refs_sha256")
                or saved.get("metadata", {}).get("signal_date") != grant.get("signal_date")
                or saved.get("metadata", {}).get("execution_date") != grant.get("execution_date")
                or saved.get("metadata", {}).get("source_refs", {}).get("selected/package.json", {}).get("sha256") != grant.get("expected_package_sha256")
                or manifest.get("strategy_id") != "HGB_DIAG_5"
                or manifest.get("provenance") != "live"
                or manifest.get("targets") != [{"code": grant.get("code"), "target_qty": grant.get("target_qty")}]
                or timestamp(manifest["asof"]) != timestamp(grant["authorized_at_utc"])
                or timestamp(manifest["expires_at"]) != timestamp(grant["deadline_utc"])
                or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or origin.get("phase") != "SELL" or origin.get("signal_date") != grant.get("signal_date")
                or clock < timestamp(grant["authorized_at_utc"])
                or (not completion_only and (clock.astimezone(ZoneInfo("America/New_York")).date().isoformat() != grant.get("execution_date")
                    or not clock < timestamp(grant["deadline_utc"])))
                or not timestamp(renewal["deadline_utc"]) <= timestamp(grant["authorized_at_utc"])
                or not timestamp(grant["deadline_utc"]) <= min(timestamp(grant["authorized_at_utc"]) + timedelta(seconds=600),
                    timestamp(saved["metadata"]["next_close_utc"]))
                or grant.get("max_spread_bps") not in {50, 60}
                or grant.get("spread_authorization") != ("ORIGINAL_50BP" if grant["max_spread_bps"] == 50 else "USER_EXPLICIT_SINGLE_SELL_60BP")
                or type(grant.get("target_qty")) is not int or grant["target_qty"] < 0
                or type(grant.get("max_sell_qty")) is not int or not 1 <= grant["max_sell_qty"] <= 1000000):
            raise ValueError("MANUAL_RESIDUAL_SELL_PERMISSION_CHANGED_OR_EXPIRED")
        audit = self.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
            ("BEST_MANUAL_RESIDUAL_SELL_AUTHORIZED", grant["authorized_at_utc"]))
        if not any(_first_execution_sha(json.loads(row[0])) == ref for row in audit):
            raise ValueError("MANUAL_RESIDUAL_SELL_AUTHORIZATION_AUDIT_CHANGED")
        number(grant.get("limit_price"), "人工卖出最低限价", .000001)
        return grant

    def _validate_first_execution_manifest(self, manifest, clock):
        # A separate typed native epoch uses this same plan/send authority seam.
        try: native_origin = json.loads(manifest.get("source", "{}"))
        except (TypeError,ValueError): native_origin = {}
        validator = getattr(self,"native_first_execution_validator",None)
        if callable(validator) and validator(manifest,clock) is not None:
            return
        if ((isinstance(native_origin,dict) and native_origin.get("native_first_execution_permission_sha256") is not None)
                or not callable(validator) and self.db.execute("SELECT 1 FROM settings WHERE key='best_native_first_execution'").fetchone()):
            raise ValueError("NATIVE_FIRST_EXECUTION_CANONICAL_OWNER_REQUIRED")
        self._manual_residual_sell_permission(manifest, clock)
        try:
            origin = json.loads(manifest.get("source", ""))
        except (ValueError, TypeError):
            origin = {}
        binding = origin.get("first_execution_permission_sha256") if isinstance(origin, dict) else None
        record = self._get("best_first_execution", None)
        if binding is None:
            if (isinstance(record, dict) and isinstance(origin, dict)
                    and origin.get("kind") == "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                    and origin.get("signal_date") == record.get("signal_date")):
                raise ValueError("SIMULATE_FIRST_EXECUTION_PERMISSION_REF_REQUIRED")
            return
        saved, capital = self._get("best_plan", {}), self._get("best_capital", {})
        if (not isinstance(record, dict) or binding != _first_execution_sha(record)
                or self._get("best_first_execution:" + record["signal_date"], None) != record
                or self.mode != "moomoo_simulate" or self.broker is None
                or self.account_id != self._get("best_account", None)
                or str(self.broker.account_id) != self.account_id
                or manifest.get("strategy_id") != "HGB_DIAG_5"
                or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or origin.get("phase") not in {"SELL", "BUY"}
                or origin.get("signal_date") != record["signal_date"]
                or any(origin.get(k) != record.get(k) for k in ("next_open_utc", "signal_close_utc", "budget"))
                or origin.get("execution_delay_minutes") != 0 or origin.get("execution_window_seconds") != 600
                or record.get("budget") != capital.get("budget")
                or record.get("unused_cash") != capital.get("unused_cash")
                or capital.get("account_id") != self.account_id):
            raise ValueError("SIMULATE_FIRST_EXECUTION_MANIFEST_INVALID")
        continuation = self._first_continuation_record("best_first_continuation", record)
        end = self._first_execution_deadline("best_first_continuation", record, plan=saved.get("plan"), metadata=saved.get("metadata", {}),
            account_id=self.account_id, clock=clock, execution_delay_minutes=self._get("execution_delay_minutes", 0),
            execution_window_seconds=self._get("execution_window_seconds", 60))
        state = self._get("best_execution", {})
        if continuation is not None:
            _validate_first_continuation_state(continuation, state)
            if (origin.get("first_continuation_permission_sha256") != _first_execution_sha(continuation)
                    or state.get("first_continuation_permission_sha256") != _first_execution_sha(continuation)
                    or any([row["code"], origin["phase"]] in continuation["completed_pairs"] for row in manifest["targets"])):
                raise ValueError("SIMULATE_FIRST_CONTINUATION_MANIFEST_INVALID")
        if (end is None or clock >= end or timestamp(manifest["expires_at"]) != end
                or state.get("first_execution_permission_sha256") != binding
                or state.get("signal_date") != record["signal_date"]
                or state.get("phase") != origin["phase"] or state.get("manifest") != manifest):
            raise ValueError("SIMULATE_FIRST_EXECUTION_EXPIRED_OR_STATE_CHANGED")

    def _paper_catchup_end(self, record, *, strategy_id, plan, batch, batch_id,
            opening, closing, signal_date, execution_date, source_refs, clock, original_end):
        """Validate the persisted one-session permission against this original book."""
        if not isinstance(record, dict) or record.get("signal_date") != signal_date or record.get("execution_date") != execution_date:
            return None  # An earlier day's permission never changes a new signal's clock.
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        renewed = record.get("reason") == "USER_REQUESTED_SAME_DAY_PAPER_CATCHUP_RENEWAL"
        if renewed:
            original = self._get("paper_same_day_catchup", None)
            prior_sha = hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
            if (not isinstance(original, dict) or record.get("prior_permission_sha256") != prior_sha
                    or self._get("paper_same_day_catchup_renewal", None) != record
                    or record.get("allowed_codes") != ["US.KDK"] or not isinstance(batch, dict)
                    or not (set(batch.get("required_codes", [])) - set(batch.get("processed_codes", []))).issubset(record["allowed_codes"])
                    or len(record.get("prior_execution_decisions", [])) != len(record.get("processed_codes", []))
                    or {row.get("code") for row in record.get("prior_execution_decisions", [])} != set(record.get("processed_codes", []))
                    or batch.get("execution_decisions", [])[:len(record.get("prior_execution_decisions", []))] != record.get("prior_execution_decisions")
                    or timestamp(record["authorized_at_utc"]) < timestamp(original["deadline_utc"])):
                raise ValueError("PAPER_CATCHUP_RENEWAL_BINDING_INVALID")
            self._paper_catchup_end(original, strategy_id=strategy_id, plan=plan, batch=batch,
                batch_id=batch_id, opening=opening, closing=closing, signal_date=signal_date,
                execution_date=execution_date, source_refs=source_refs, clock=clock, original_end=original_end)
        authorized, deadline = timestamp(record["authorized_at_utc"]), timestamp(record["deadline_utc"])
        market_open, session_close = timestamp(record["market_open_utc"]), timestamp(record["next_close_utc"])
        plan_hash = hashlib.sha256(json.dumps(plan, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        if (not self.paper_only or self.mode != "paper" or self.broker is not None
                or self.halt_event.is_set() or not isinstance(batch, dict)
                or batch.get("policy") != "QUALIFIED_QUOTES_ONLY"
                or batch.get("batch_id") != batch_id or batch.get("strategy_id") != strategy_id
                or batch.get("signal_date") != signal_date or batch.get("execution_date") != execution_date
                or batch.get("status") not in {"WAITING_QUOTES", "PARTIALLY_EXECUTED", "EXECUTED"}
                or record.get("reason") not in {"USER_REQUESTED_SAME_DAY_PAPER_CATCHUP",
                                              "USER_REQUESTED_SAME_DAY_PAPER_CATCHUP_RENEWAL"}
                or record.get("batch_id") != batch_id or record.get("strategy_id") != strategy_id
                or record.get("account_id") != self.paper_account_id or self.account_id != self.paper_account_id
                or self._get("paper_account_identity", None) != self.paper_account_id
                or record.get("source_plan_sha256") != plan_hash or batch.get("source_plan_sha256") != plan_hash
                or batch.get("source_plan") != plan or record.get("source_refs") != source_refs or batch.get("source_refs") != source_refs
                or not isinstance(source_refs, dict) or not source_refs
                or record.get("pretrade_equity") is None or record.get("pretrade_equity") != batch.get("pretrade_equity")
                or record.get("required_codes") != batch.get("required_codes")
                or not set(record.get("processed_codes", [])).issubset(batch.get("processed_codes", []))
                or not set(batch.get("processed_codes", [])).issubset(batch.get("required_codes", []))
                or timestamp(record["execution_time_utc"]) != opening or timestamp(record["signal_close_utc"]) != closing
                or timestamp(record["original_deadline_utc"]) != original_end
                or not market_open <= opening <= original_end <= authorized <= clock
                or not authorized < deadline <= min(authorized + timedelta(seconds=600), session_close)
                or market_open.astimezone(ny).date().isoformat() != execution_date
                or session_close.astimezone(ny).date().isoformat() != execution_date
                or authorized.astimezone(ny).date().isoformat() != execution_date
                or clock.astimezone(ny).date().isoformat() != execution_date
                or closing.astimezone(ny).date().isoformat() != signal_date
                or deadline.astimezone(ny).date().isoformat() != execution_date):
            raise ValueError("PAPER_CATCHUP_BINDING_INVALID")
        override = record.get("single_sell_override")
        if override is not None:
            audit = {json.loads(row[0]).get("permission_sha256") for row in self.db.execute(
                "SELECT detail FROM audit WHERE event='PAPER_SINGLE_SELL_SPREAD_AUTHORIZED'")}
            held = self._get("paper", {}).get("positions", {}).get("US.KDK", 0)
            weight = next((row["target_weight"] for row in plan["rows"] if row["code"] == "US.KDK"), 0)
            if (not renewed or not isinstance(override, dict)
                    or set(override) != {"code", "side", "target_qty", "max_qty", "spread_bps"}
                    or override.get("code") != "US.KDK" or override.get("side") != "SELL"
                    or type(override.get("target_qty")) is not int or override["target_qty"] != 0
                    or type(override.get("spread_bps")) is not int or override["spread_bps"] != 60
                    or type(override.get("max_qty")) is not int or override["max_qty"] <= 0
                    or type(held) is not int or not 0 <= held <= override["max_qty"] or weight != 0
                    or strategy_id not in {"HGB_DIAG_5", "HGB_FACTOR_5"}
                    or _first_execution_sha(record) not in audit):
                raise ValueError("PAPER_SINGLE_SELL_OVERRIDE_BINDING_INVALID")
        return deadline

    def _paper_automatic_completion_end(self, policy, *, strategy_id, clock,
            opening, closing, signal_date, execution_date, next_close_utc, source_refs,
            execution_window_seconds):
        """Use the standing owner policy without creating or altering manual grants."""
        current = self._automatic_completion_policy(clock, strategy_id,
            expected_policy=policy, execution_date=execution_date)
        if current is None:
            return None
        from zoneinfo import ZoneInfo
        ny = ZoneInfo("America/New_York")
        session_close = timestamp(next_close_utc)
        opening_times = (((9, 55, 0, 0),) if current["schema_version"] == 2
            else ((9, 30, 0, 0), (10, 0, 0, 0)))
        if (execution_window_seconds != current["priority_window_seconds"]
                or not "2026-01-01" <= signal_date < execution_date < current["evaluation_end_exclusive"]
                or opening.astimezone(ny).date().isoformat() != execution_date
                or clock.astimezone(ny).date().isoformat() != execution_date
                or closing.astimezone(ny).date().isoformat() != signal_date
                or (opening.astimezone(ny).hour, opening.astimezone(ny).minute,
                    opening.astimezone(ny).second, opening.microsecond) not in opening_times
                or session_close.astimezone(ny).date().isoformat() != execution_date
                or session_close <= opening + timedelta(seconds=1200)
                or (current["schema_version"] == 2 and session_close <=
                    opening + timedelta(seconds=current["priority_window_seconds"]))
                or closing >= opening or closing > clock
                or not isinstance(source_refs, dict) or not source_refs):
            raise ValueError("PAPER_AUTOMATIC_COMPLETION_SESSION_BINDING_INVALID")
        if current["schema_version"] == 2:
            return opening + timedelta(seconds=current["priority_window_seconds"])
        return session_close - timedelta(seconds=current["close_buffer_seconds"])

    def paper_rebalance(self, strategy_id, plan, quotes, *, now, next_open_utc,
                        signal_date, execution_date, signal_close_utc, source_refs=None,
                        fee_bps=5, allow_partial_quotes=False, quote_errors=None,
                        execution_window_seconds=60, automatic_completion_policy=None,
                        next_close_utc=None):
        """Atomic local fills for one calendar-gated cohort signal. No broker methods exist here.

        The frozen weights remain in the batch record. Integer shares use the observed
        bid/ask; sales settle before purchases, and each purchase reserves its actual fee.
        This route deliberately does not inherit the manual demo's exposure/order caps.
        """
        started_monotonic = time.monotonic()
        with self.lock:
            if not self.paper_only or self.mode != "paper" or self.broker is not None:
                raise ValueError("独立策略执行仅允许永久纸面账户")
            if self.halt_event.is_set() or self.cancel_step.is_set():
                raise ValueError("纸面账户已停止或锁定")
            clock = timestamp(now.isoformat()) if isinstance(now, datetime) else timestamp(now)
            opening, closing = timestamp(next_open_utc), timestamp(signal_close_utc)
            if type(allow_partial_quotes) is not bool:
                raise ValueError("部分报价执行选项必须为布尔值")
            if (type(execution_window_seconds) is not int or not
                    (1 <= execution_window_seconds <= 600 or execution_window_seconds == 1500)):
                raise ValueError("纸面计划执行窗口必须为1至600秒，或09:55起的1500秒整数")
            if execution_window_seconds == 1500:
                from zoneinfo import ZoneInfo
                local_opening = opening.astimezone(ZoneInfo("America/New_York"))
                if (local_opening.hour, local_opening.minute, local_opening.second,
                        local_opening.microsecond) != (9, 55, 0, 0):
                    raise ValueError("PAPER_ORDINARY_CLOCK_PAIR_INVALID")
            original_end = opening + timedelta(seconds=execution_window_seconds)
            batch_id = self._paper_batch_id(strategy_id, signal_date, execution_date)
            existing = self.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
            if closing >= opening or closing > clock:
                raise ValueError("MISSED_OPEN_OR_INVALID_SIGNAL_CLOCK")
            auto_policy, auto_end = None, None
            if automatic_completion_policy is not None:
                auto_end = self._paper_automatic_completion_end(automatic_completion_policy,
                    strategy_id=strategy_id, clock=clock, opening=opening, closing=closing,
                    signal_date=signal_date, execution_date=execution_date, next_close_utc=next_close_utc,
                    source_refs=source_refs or {}, execution_window_seconds=execution_window_seconds)
                if auto_end is not None:
                    if not allow_partial_quotes or not opening <= clock < auto_end:
                        raise ValueError("PAPER_AUTOMATIC_COMPLETION_WINDOW_CLOSED")
                    auto_policy = automatic_completion_policy
            first_permission_sha = None
            single_sell_permission = None
            if auto_end is None and not opening <= clock < original_end:
                first_permission = self._get("paper_first_execution", None)
                if (isinstance(first_permission, dict) and first_permission.get("signal_date") == signal_date
                        and self._get("paper_first_execution:" + signal_date, None) != first_permission):
                    raise ValueError("PAPER_FIRST_EXECUTION_IMMUTABLE_PERMISSION_CHANGED")
                first_end = self._paper_first_execution_end(first_permission, strategy_id=strategy_id,
                    plan=plan, batch=json.loads(existing[0]) if existing else None, batch_id=batch_id,
                    metadata=dict(signal_date=signal_date, execution_date=execution_date,
                        next_open_utc=next_open_utc, signal_close_utc=signal_close_utc,
                        next_close_utc=first_permission.get("next_close_utc") if isinstance(first_permission, dict) else None,
                        source_refs=source_refs or {}), clock=clock, execution_window_seconds=execution_window_seconds)
                if first_end is not None:
                    if not allow_partial_quotes or not opening <= clock < first_end:
                        raise ValueError("FIRST_EXECUTION_EXPIRED")
                    first_permission_sha = _first_execution_sha(first_permission)
            if auto_end is None and not opening <= clock < original_end and first_permission_sha is None:
                permission = self._get("paper_same_day_catchup_renewal", None)
                if (not isinstance(permission, dict) or permission.get("signal_date") != signal_date
                        or permission.get("execution_date") != execution_date):
                    permission = self._get("paper_same_day_catchup", None)
                end = self._paper_catchup_end(permission,
                    strategy_id=strategy_id, plan=plan, batch=json.loads(existing[0]) if existing else None,
                    batch_id=batch_id, opening=opening, closing=closing, signal_date=signal_date,
                    execution_date=execution_date, source_refs=source_refs or {}, clock=clock, original_end=original_end)
                if not allow_partial_quotes or end is None or not opening <= clock < end:
                    raise ValueError("MISSED_OPEN_OR_INVALID_SIGNAL_CLOCK")
                if permission.get("single_sell_override") is not None:
                    single_sell_permission = permission
            if signal_date >= execution_date or plan.get("source_date", signal_date) != signal_date:
                raise ValueError("信号日和执行日不一致")
            if type(fee_bps) not in (int, float) or fee_bps != 5:
                raise ValueError("冻结纸面费用假设固定为单边5bp")
            fee_rate = .0005
            if existing and not allow_partial_quotes:
                return dict(json.loads(existing[0]), already_executed=True)
            rows = plan.get("rows")
            if not isinstance(rows, list):
                raise ValueError("目标行必须为列表")
            weights = {}
            for row in rows:
                code = row.get("code")
                if not code_valid(code) or code in weights:
                    raise ValueError("目标代码不合法或重复")
                weights[code] = number(row["target_weight"], "目标权重")
                if weights[code] > 1:
                    raise ValueError("目标权重超过1")
            holds = exact_hold_units(plan)
            target_cash = number(plan["target_cash_weight"], "目标现金权重")
            if abs(sum(weights.values()) + target_cash - 1) > 1e-8:
                raise ValueError("目标权重和现金不归一")
            if allow_partial_quotes:
                return self._paper_partial_rebalance(strategy_id, plan, quotes,
                    quote_errors=quote_errors, clock=clock, opening=opening,
                    signal_date=signal_date, execution_date=execution_date,
                    source_refs=source_refs or {}, weights=weights, target_cash=target_cash,
                    batch_id=batch_id, existing=json.loads(existing[0]) if existing else None,
                    first_execution_permission_sha256=first_permission_sha,
                    started_monotonic=started_monotonic, single_sell_permission=single_sell_permission,
                    automatic_completion_policy=auto_policy, next_close_utc=next_close_utc,
                    signal_close_utc=signal_close_utc, execution_window_seconds=execution_window_seconds)
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0})
            holdings = dict(ledger["positions"])
            if any(holdings.get(code, 0) != qty for code, qty in holds.items()):
                raise ValueError("EXACT_HOLD_UNITS_CHANGED")
            codes = {c for c, w in weights.items() if w} | {c for c, q in holdings.items() if q}
            validated = {}
            for code in codes:
                quote = quotes.get(code)
                if not isinstance(quote, dict):
                    raise ValueError("真实行情缺失: " + code)
                p = number(quote["price"], "真实最新价", 1e-12)
                bid, ask = number(quote["bid"], "买一", 1e-12), number(quote["ask"], "卖一", 1e-12)
                asof = timestamp(quote["asof"])
                if not opening <= asof <= clock + timedelta(seconds=2) or not -2 <= (clock - asof).total_seconds() <= 60:
                    raise ValueError("真实行情过期或不属于当前开盘窗口: " + code)
                if quote.get("tradable") is not True or quote.get("currency", "USD") != "USD" or quote.get("market", "US") != "US":
                    raise ValueError("证券当前不可交易: " + code)
                if bid > ask or (ask - bid) / p * 10000 > 50:
                    raise ValueError("真实盘口价差无效: " + code)
                if quote.get("lot_size", 1) != 1:
                    raise ValueError("仅支持美股整数股: " + code)
                validated[code] = dict(price=p, bid=bid, ask=ask, asof=asof.isoformat(),
                    source=quote.get("source", "MOOMOO_OPEND"))
            equity = number(ledger["cash"], "纸面现金") + sum(q * validated[c]["price"] for c, q in holdings.items() if q)
            if equity <= 0:
                raise ValueError("纸面权益必须为正")
            desired = {code: int((Decimal(str(weights.get(code, 0))) * Decimal(str(equity)) /
                Decimal(str(validated[code]["ask"]))).to_integral_value(rounding=ROUND_FLOOR)) for code in codes}
            desired.update(holds)
            cash, fees = float(ledger["cash"]), float(ledger.get("fees", 0.0))
            fills = []
            # Precompute and validate the entire transaction before changing either ledger or orders.
            for side in ("SELL", "BUY"):
                for code in sorted(codes, key=lambda c: (-weights.get(c, 0), c)):
                    delta = desired[code] - holdings.get(code, 0)
                    if (side == "SELL" and delta >= 0) or (side == "BUY" and delta <= 0):
                        continue
                    quote = validated[code]
                    price = quote["bid"] if side == "SELL" else quote["ask"]
                    qty = abs(delta)
                    if side == "BUY":
                        affordable = int((Decimal(str(max(0, cash))) / (Decimal(str(price)) *
                            Decimal("1.0005"))).to_integral_value(rounding=ROUND_FLOOR))
                        qty = min(qty, affordable)
                    if not qty:
                        continue
                    notional, fee = qty * price, qty * price * fee_rate
                    cash += notional - fee if side == "SELL" else -notional - fee
                    fees += fee
                    holdings[code] = holdings.get(code, 0) + (qty if side == "BUY" else -qty)
                    if cash < -1e-8 or holdings[code] < 0:
                        raise ValueError("纸面现金或持仓约束失败")
                    key = hashlib.sha256((batch_id + ":" + code).encode()).hexdigest()[:32]
                    fills.append(dict(id=key, strategy_id=strategy_id, account_id=self.paper_account_id,
                        mode="paper", paper=True, code=code, ticker=code.removeprefix("US."), side=side,
                        qty=qty, fill_price=price, limit_price=price, notional=notional, fee=fee,
                        fee_bps=5, filled_at=clock.isoformat(), signal_date=signal_date,
                        execution_date=execution_date, quote_asof=quote["asof"], source=quote["source"],
                        signal_source_refs=source_refs or {}, order_status="FILLED", status="FILLED",
                        order_id="paper-" + key, sequence=len(fills)))
            ledger = dict(cash=max(0, cash), positions={c: q for c, q in holdings.items() if q}, fees=fees)
            result = dict(batch_id=batch_id, strategy_id=strategy_id, signal_date=signal_date,
                execution_date=execution_date, status="EXECUTED", filled_at=clock.isoformat(),
                pretrade_equity=equity, target_cash_weight=target_cash, target_weights=weights,
                fill_count=len(fills), fee=sum(fill["fee"] for fill in fills), source_refs=source_refs or {},
                fee_bps=5, paper=True, already_executed=False)
            if self.halt_event.is_set() or self.cancel_step.is_set():
                raise ValueError("纸面成交前已收到停止请求")
            try:
                self.db.execute("BEGIN IMMEDIATE")
                for fill in fills:
                    self.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (fill["id"],
                        fill["filled_at"], strategy_id, "paper", self.paper_account_id, fill["code"],
                        fill["side"], fill["qty"], fill["fill_price"], "FILLED", fill["order_id"]))
                    self.db.execute("INSERT INTO paper_fills VALUES (?,?)", (fill["id"], json.dumps(fill)))
                self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("paper", json.dumps(ledger)))
                self.db.execute("INSERT INTO paper_batches VALUES (?,?)", (batch_id, json.dumps(result)))
                if self.halt_event.is_set() or self.cancel_step.is_set():
                    raise ValueError("纸面事务提交前已收到停止请求")
                self.db.commit()
            except Exception:
                self.db.rollback()
                raise
            self._audit("PAPER_COHORT_FILLED", json.dumps(result))
            book = self.paper_mark(quotes, day=execution_date)
            self._observe_paper_equity(book["equity"], clock.isoformat())
            return result

    def _paper_partial_rebalance(self, strategy_id, plan, quotes, *, quote_errors,
            clock, opening, signal_date, execution_date, source_refs, weights,
            target_cash, batch_id, existing, first_execution_permission_sha256=None, started_monotonic=None,
            single_sell_permission=None, automatic_completion_policy=None, next_close_utc=None,
            signal_close_utc=None, execution_window_seconds=60):
        """Commit qualified symbols only; unqualified allocations remain unspent.

        Each symbol keeps its frozen target. Failed
        quotes stay pending within the caller's calendar window. The first fully
        verified account valuation fixes the sizing basis across those attempts.
        Recorded marks retain their actual source time and are never called live.
        """
        if not isinstance(quotes, dict) or (quote_errors is not None and not isinstance(quote_errors, dict)):
            raise ValueError("部分报价和逐证券错误必须为对象")
        frozen_plan = json.loads(json.dumps(plan, ensure_ascii=False, allow_nan=False))
        plan_hash = hashlib.sha256(json.dumps(frozen_plan, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if existing:
            if existing.get("policy") != "QUALIFIED_QUOTES_ONLY":
                return dict(existing, already_executed=True)
            if existing.get("source_plan_sha256") != plan_hash or existing.get("source_refs") != source_refs:
                raise ValueError("同一信号的冻结计划或来源已改变")
            if existing.get("status") == "EXECUTED":
                return dict(existing, already_executed=True, new_fill_count=0)
        old = existing or {}
        auto_source_sha = _first_execution_sha(source_refs) if automatic_completion_policy is not None else None
        auto_policy_sha = (_first_execution_sha(automatic_completion_policy)
                           if automatic_completion_policy is not None else None)
        if old.get("automatic_completion_policy_sha256") is not None and (
                auto_policy_sha != old["automatic_completion_policy_sha256"]
                or timestamp(next_close_utc) != timestamp(old["automatic_completion_next_close_utc"])):
            raise ValueError("PAPER_AUTOMATIC_COMPLETION_BATCH_POLICY_CHANGED")
        ledger = self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0})
        holdings = dict(ledger["positions"])
        if any(not code_valid(code) or type(qty) is not int or qty < 0 for code, qty in holdings.items()):
            raise ValueError("独立纸面账本必须为有效美股代码和非负整数股")
        holds = exact_hold_units(plan)
        if any(holdings.get(code, 0) != qty for code, qty in holds.items()):
            raise ValueError("EXACT_HOLD_UNITS_CHANGED")
        required = set(old.get("required_codes", [])) | {c for c, w in weights.items() if w}
        required.update(c for c, qty in holdings.items() if qty)
        processed = set(old.get("processed_codes", []))
        if automatic_completion_policy is not None and existing and required != set(old.get("required_codes", [])):
            raise ValueError("PAPER_AUTOMATIC_COMPLETION_REQUIRED_CODES_CHANGED")
        processed.update(set(holds) & required)
        pending = required - processed
        resolved_targets = dict(old.get("pending_targets", {})) if automatic_completion_policy is not None else {}
        fill_counts = dict(old.get("code_fill_counts", {})) if automatic_completion_policy is not None else {}
        if (set(resolved_targets) - required
                or any(type(qty) is not int or qty < 0 for qty in resolved_targets.values())
                or set(fill_counts) - required
                or any(type(count) is not int or count < 0 for count in fill_counts.values())):
            raise ValueError("PAPER_AUTOMATIC_COMPLETION_TARGET_PROGRESS_INVALID")
        override = single_sell_permission.get("single_sell_override") if single_sell_permission else None
        if override is not None and (required != set(old.get("required_codes", []))
                or not pending.issubset({"US.KDK"}) or weights.get("US.KDK", 0) != 0):
            raise ValueError("PAPER_SINGLE_SELL_SCOPE_CHANGED")
        validated, failures = {}, {}
        for code in sorted(required):
            try:
                if code in (quote_errors or {}):
                    raise ValueError(str(quote_errors[code])[:512])
                quote = quotes.get(code)
                if not isinstance(quote, dict):
                    raise ValueError("真实行情缺失")
                price = number(quote["price"], "真实最新价", 1e-12)
                bid, ask = number(quote["bid"], "买一", 1e-12), number(quote["ask"], "卖一", 1e-12)
                asof = timestamp(quote["asof"])
                if not opening <= asof <= clock or not 0 <= (clock - asof).total_seconds() <= 30:
                    raise ValueError("真实行情过期或不属于当前执行窗口（最长30秒）")
                if (quote.get("tradable") is not True or quote.get("currency", "USD") != "USD"
                        or quote.get("market", "US") != "US"):
                    raise ValueError("证券当前不可交易")
                if (override is not None and code == override["code"] and code in pending
                        and abs(bid / price - 1) > .02):
                    raise ValueError("单证券卖出价偏离真实最新价超过2%")
                spread_limit = (override["spread_bps"] if override is not None
                                and code == override["code"] and code in pending else 50)
                if automatic_completion_policy is not None:
                    from .strategy import auto_completion_spread_is_valid
                    spread_quote = quote if automatic_completion_policy["one_tick_spread"] else {
                        **quote, "price_tick": None, "tick_size": None}
                    if (abs(bid / price - 1) > automatic_completion_policy["price_deviation_fraction"]
                            or abs(ask / price - 1) > automatic_completion_policy["price_deviation_fraction"]):
                        raise ValueError("自动执行盘口偏离真实最新价超过2%")
                    if not auto_completion_spread_is_valid(spread_quote):
                        raise ValueError("自动执行盘口价差无效（通常50bp，真实一档且最多200bp）")
                elif bid > ask or (ask - bid) / price * 10000 > spread_limit:
                    raise ValueError(f"真实盘口价差无效（上限{spread_limit}bp）")
                if quote.get("lot_size", 1) != 1:
                    raise ValueError("仅支持美股整数股")
                validated[code] = dict(price=price, bid=bid, ask=ask,
                    asof=asof.isoformat(), source=quote.get("source", "MOOMOO_OPEND"),
                    **({"price_tick": quote.get("price_tick", quote.get("tick_size"))}
                       if automatic_completion_policy is not None else {}))
            except (ValueError, KeyError, TypeError) as exc:
                if code in pending:
                    failures[code] = str(exc)

        equity = old.get("pretrade_equity")
        valuation_basis = old.get("pretrade_valuation_basis")
        valuation_marks = old.get("pretrade_valuation_marks", {})
        valuation_asof = old.get("pretrade_equity_asof")
        missing_marks = []
        if equity is None:
            equity = number(ledger["cash"], "纸面现金")
            recorded = self._get("paper_marks", {})
            valuation_marks, reused_mark = {}, False
            for code, qty in sorted(holdings.items()):
                if not qty:
                    continue
                quote = validated.get(code)
                if quote:
                    valuation_marks[code] = dict(qty=qty, price=quote["price"],
                        asof=quote["asof"], source=quote["source"], basis="MOOMOO_REALTIME")
                else:
                    mark = recorded.get(code, {})
                    try:
                        mark_price = number(mark["price"], "已记录真实标价", 1e-12)
                        mark_asof = timestamp(mark["asof"])
                        if (mark_asof > clock or mark.get("basis") not in {"MOOMOO_REALTIME", "SIGNAL_CLOSE"}
                                or not mark.get("source") or mark["source"] == "UNKNOWN"):
                            raise ValueError("持仓已记录标价的来源或时间不可核验")
                        valuation_marks[code] = dict(qty=qty, price=mark_price,
                            asof=mark_asof.isoformat(), source=mark["source"], basis=mark["basis"])
                        reused_mark = True
                    except (ValueError, KeyError, TypeError):
                        missing_marks.append(code)
                        continue
                equity += qty * valuation_marks[code]["price"]
            if missing_marks:
                equity, valuation_basis = None, "INCOMPLETE"
            elif equity <= 0:
                raise ValueError("纸面权益必须为正")
            else:
                valuation_basis = "RECORDED_MARKS" if reused_mark else (
                    "MOOMOO_REALTIME" if valuation_marks else "CASH_LEDGER")
            valuation_asof = min((mark["asof"] for mark in valuation_marks.values()),
                key=timestamp, default=None)
        else:
            number(equity, "冻结纸面下单权益", 1e-12)

        desired, decisions = {}, list(old.get("execution_decisions", []))
        recorded_holds = {row.get("code") for row in decisions if row.get("reason") == "HOLD_EXACT_UNITS"}
        decisions.extend(dict(code=code, at=clock.isoformat(), target_qty=qty,
            qty_before=qty, qty_after=qty, reason="HOLD_EXACT_UNITS")
            for code, qty in holds.items() if code in required and code not in recorded_holds)
        for code in sorted(pending):
            if code not in validated:
                continue
            if equity is None and weights.get(code, 0):
                failures[code] = "账户下单权益未能完整核验；缺少持仓真实标价: " + ", ".join(missing_marks)
                continue
            if code in resolved_targets:
                desired[code] = resolved_targets[code]
            else:
                desired[code] = 0 if not weights.get(code, 0) else int((
                    Decimal(str(weights[code])) * Decimal(str(equity)) /
                    Decimal(str(validated[code]["ask"]))).to_integral_value(rounding=ROUND_FLOOR))
                if automatic_completion_policy is not None:
                    resolved_targets[code] = desired[code]
        cash, fees = float(ledger["cash"]), float(ledger.get("fees", 0.0))
        fills, filled_codes = [], set(old.get("executed_codes", []))
        original_holdings = dict(holdings)
        for side in ("SELL", "BUY"):
            for code in sorted(desired, key=lambda c: (-weights.get(c, 0), c)):
                delta = desired[code] - holdings.get(code, 0)
                if (side == "SELL" and delta >= 0) or (side == "BUY" and delta <= 0):
                    continue
                quote = validated[code]
                price = quote["bid"] if side == "SELL" else quote["ask"]
                qty = abs(delta)
                if side == "BUY":
                    affordable = int((Decimal(str(max(0, cash))) /
                        (Decimal(str(price)) * Decimal("1.0005"))).to_integral_value(rounding=ROUND_FLOOR))
                    qty = min(qty, affordable)
                if not qty:
                    continue
                notional, fee = qty * price, qty * price * .0005
                cash += notional - fee if side == "SELL" else -notional - fee
                fees += fee
                holdings[code] = holdings.get(code, 0) + (qty if side == "BUY" else -qty)
                if cash < -1e-8 or holdings[code] < 0:
                    raise ValueError("纸面现金或持仓约束失败")
                fill_identity = batch_id + ":" + code
                if automatic_completion_policy is not None:
                    count = fill_counts.get(code, 0)
                    if count:
                        fill_identity += ":remainder:" + str(count)
                    fill_counts[code] = count + 1
                key = hashlib.sha256(fill_identity.encode()).hexdigest()[:32]
                fills.append(dict(id=key, strategy_id=strategy_id, account_id=self.paper_account_id,
                    mode="paper", paper=True, code=code, ticker=code.removeprefix("US."), side=side,
                    qty=qty, fill_price=price, limit_price=price, notional=notional, fee=fee,
                    fee_bps=5, filled_at=clock.isoformat(), signal_date=signal_date,
                    execution_date=execution_date, quote_asof=quote["asof"], source=quote["source"],
                    signal_source_refs=source_refs, source_plan_sha256=plan_hash,
                    order_status="FILLED", status="FILLED", order_id="paper-" + key, sequence=len(fills),
                    **({"automatic_completion_policy_sha256": auto_policy_sha,
                        "quote_price": quote["price"], "quote_bid": quote["bid"],
                        "quote_ask": quote["ask"], "quote_price_tick": quote.get("price_tick")}
                       if automatic_completion_policy is not None else {})))
                filled_codes.add(code)
        for code in sorted(desired):
            if automatic_completion_policy is not None and holdings.get(code, 0) != desired[code]:
                failures[code] = "CASH_CONSTRAINT: 等待真实可用资金；固定目标" + str(desired[code]) + "股，当前" + str(holdings.get(code, 0)) + "股"
                continue
            processed.add(code)
            decisions.append(dict(code=code, at=clock.isoformat(), target_qty=desired[code],
                qty_before=original_holdings.get(code, 0), qty_after=holdings.get(code, 0),
                reason="FILLED" if any(fill["code"] == code for fill in fills) else (
                    "TARGET_SATISFIED" if original_holdings.get(code, 0) == desired[code] else "CASH_CONSTRAINT")))
            failures.pop(code, None)
        skipped = [dict(code=code, reason=failures.get(code, "真实行情缺失"))
                   for code in sorted(required - processed)]
        status = "EXECUTED" if not skipped else "PARTIALLY_EXECUTED" if (processed or (
            automatic_completion_policy is not None and filled_codes)) else "WAITING_QUOTES"
        result = dict(batch_id=batch_id, strategy_id=strategy_id, signal_date=signal_date,
            execution_date=execution_date, status=status, policy="QUALIFIED_QUOTES_ONLY",
            filled_at=clock.isoformat() if fills else old.get("filled_at"), last_attempt_at=clock.isoformat(),
            pretrade_equity=equity, pretrade_valuation_basis=valuation_basis,
            pretrade_valuation_marks=valuation_marks, pretrade_equity_asof=valuation_asof,
            target_cash_weight=target_cash, target_weights=weights,
            source_plan=frozen_plan, source_plan_sha256=plan_hash, source_refs=source_refs,
            required_codes=sorted(required), processed_codes=sorted(processed), executed_codes=sorted(filled_codes),
            skipped=skipped, reason="; ".join(row["code"] + ": " + row["reason"] for row in skipped),
            fill_count=old.get("fill_count", 0) + len(fills), new_fill_count=len(fills),
            fee=old.get("fee", 0) + sum(fill["fee"] for fill in fills),
            attempts=old.get("attempts", 0) + 1, execution_decisions=decisions,
            fee_bps=5, paper=True, already_executed=False)
        if automatic_completion_policy is not None:
            result.update(automatic_completion_policy_sha256=auto_policy_sha,
                automatic_completion_next_close_utc=timestamp(next_close_utc).isoformat(),
                pending_targets=resolved_targets, code_fill_counts=fill_counts)
        if first_execution_permission_sha256 is not None:
            result["first_execution_permission_sha256"] = first_execution_permission_sha256
            continuation = self._first_continuation_record("paper_first_continuation", self._get("paper_first_execution", None))
            if continuation is not None:
                result["first_continuation_permission_sha256"] = _first_execution_sha(continuation)
        if self.halt_event.is_set() or self.cancel_step.is_set():
            raise ValueError("纸面成交前已收到停止请求")
        updated = dict(cash=max(0, cash), positions={c: q for c, q in holdings.items() if q}, fees=fees)
        try:
            self.db.execute("BEGIN IMMEDIATE")
            if automatic_completion_policy is not None:
                commit_clock = clock + timedelta(seconds=max(0, time.monotonic() - started_monotonic))
                end = self._paper_automatic_completion_end(automatic_completion_policy,
                    strategy_id=strategy_id, clock=commit_clock, opening=opening,
                    closing=timestamp(signal_close_utc), signal_date=signal_date,
                    execution_date=execution_date, next_close_utc=next_close_utc,
                    source_refs=source_refs, execution_window_seconds=execution_window_seconds)
                if (end is None or not opening <= commit_clock < end
                        or _first_execution_sha(plan) != plan_hash
                        or _first_execution_sha(source_refs) != auto_source_sha or any(
                        not 0 <= (commit_clock - timestamp(q["asof"])).total_seconds() <= 30
                        for q in validated.values())):
                    raise ValueError("PAPER_AUTOMATIC_COMPLETION_EXPIRED_BEFORE_COMMIT")
            if single_sell_permission is not None:
                commit_clock = clock + timedelta(seconds=max(0, time.monotonic() - started_monotonic))
                end = self._paper_catchup_end(single_sell_permission, strategy_id=strategy_id,
                    plan=plan, batch=old, batch_id=batch_id, opening=opening,
                    closing=timestamp(single_sell_permission["signal_close_utc"]), signal_date=signal_date,
                    execution_date=execution_date, source_refs=source_refs, clock=commit_clock,
                    original_end=timestamp(single_sell_permission["original_deadline_utc"]))
                if (end is None or commit_clock >= end
                        or any(fill["code"] != "US.KDK" or fill["side"] != "SELL"
                               or fill["qty"] > override["max_qty"] for fill in fills)
                        or ("US.KDK" in validated and not 0 <=
                            (commit_clock - timestamp(validated["US.KDK"]["asof"])).total_seconds() <= 30)):
                    raise ValueError("PAPER_SINGLE_SELL_EXPIRED_OR_CHANGED_BEFORE_COMMIT")
            if first_execution_permission_sha256 is not None:
                # Includes time blocked acquiring the SQLite write transaction. No clock rewrite.
                commit_clock = clock + timedelta(seconds=max(0, time.monotonic() - started_monotonic))
                permission = self._get("paper_first_execution", None)
                if _first_execution_sha(permission) != first_execution_permission_sha256:
                    raise ValueError("PAPER_FIRST_EXECUTION_PERMISSION_CHANGED_BEFORE_COMMIT")
                end = self._first_execution_deadline("paper_first_continuation", permission, plan=plan,
                    metadata={key: permission[key] for key in ("signal_date", "execution_date", "next_open_utc",
                        "signal_close_utc", "next_close_utc", "source_refs")}, account_id=self.paper_account_id,
                    clock=commit_clock, execution_delay_minutes=0, execution_window_seconds=600)
                if end is None or commit_clock >= end or any(
                        not 0 <= (commit_clock - timestamp(q["asof"])).total_seconds() <= 30
                        for q in validated.values()):
                    raise ValueError("PAPER_FIRST_EXECUTION_EXPIRED_BEFORE_COMMIT")
            for fill in fills:
                self.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (fill["id"],
                    fill["filled_at"], strategy_id, "paper", self.paper_account_id, fill["code"],
                    fill["side"], fill["qty"], fill["fill_price"], "FILLED", fill["order_id"]))
                self.db.execute("INSERT INTO paper_fills VALUES (?,?)", (fill["id"], json.dumps(fill)))
            self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("paper", json.dumps(updated)))
            self.db.execute("INSERT OR REPLACE INTO paper_batches VALUES (?,?)", (batch_id, json.dumps(result)))
            if self.halt_event.is_set() or self.cancel_step.is_set():
                raise ValueError("纸面事务提交前已收到停止请求")
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self._audit("PAPER_QUALIFIED_QUOTES", json.dumps(result, ensure_ascii=False))
        # Rejecting a quote for execution also prevents it from becoming a fresh mark.
        book = self.paper_mark(validated)
        if book["equity"] is not None and (self.paper_inception_date is None
                                            or execution_date >= self.paper_inception_date):
            marks = self._get("paper_marks", {})
            held_codes = set(updated["positions"])
            current_marks = {code: marks[code] for code in sorted(held_codes)}
            nav_basis = "CASH_LEDGER" if not held_codes else (
                "MOOMOO_REALTIME" if held_codes.issubset(validated)
                else "PARTIAL_REALTIME_WITH_RECORDED_MARKS")
            payload = dict(date=execution_date, cash=book["cash"], equity=book["equity"],
                nav=book["equity"] / 10000.0, fees=book["fees"], basis=nav_basis,
                asof=min((mark["asof"] for mark in current_marks.values()), key=timestamp, default=None),
                sources=sorted({mark["source"] for mark in current_marks.values()}),
                valuation_marks=current_marks, paper=True)
            self.db.execute("INSERT OR REPLACE INTO paper_nav VALUES (?,?)", (execution_date, json.dumps(payload)))
            self.db.commit()
        return result

    @staticmethod
    def _display_payload_sql(compact):
        if type(compact) is not bool:
            raise ValueError("展示投影选项必须为布尔值")
        if not compact:
            return "payload", ()
        from .server import _APPLIED_DISPLAY_OMITTED_RECORD_FIELDS
        paths = tuple("$."+key for key in sorted(_APPLIED_DISPLAY_OMITTED_RECORD_FIELDS))
        return "json_remove(payload,"+",".join("?" for _ in paths)+")", paths

    def paper_trades(self, limit=None, *, compact=False):
        with self.lock:
            column, arguments = self._display_payload_sql(compact)
            if limit is None:
                if compact:
                    raise ValueError("展示成交读取必须明确限定条数")
                return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM paper_fills ORDER BY rowid")]
            if type(limit) is not int or limit < 1:
                raise ValueError("成交记录条数必须为正整数")
            rows = self.db.execute("SELECT "+column+" FROM paper_fills ORDER BY rowid DESC LIMIT ?", arguments+(limit,)).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]

    def paper_nav_history(self, limit=None, *, compact=False):
        with self.lock:
            column, arguments = self._display_payload_sql(compact)
            if limit is None:
                if compact:
                    raise ValueError("展示净值读取必须明确限定条数")
                return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM paper_nav ORDER BY day")]
            if type(limit) is not int or limit < 1:
                raise ValueError("净值记录条数必须为正整数")
            rows = self.db.execute("SELECT "+column+" FROM paper_nav ORDER BY day DESC LIMIT ?", arguments+(limit,)).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]

    def _manifest(self):
        row = self.db.execute("SELECT payload FROM strategies WHERE id=?", (self.active,)).fetchone()
        if not row:
            raise ValueError("请先导入并选择策略")
        return validate_manifest(json.loads(row[0]))

    def _automatic_broker_completion(self, manifest, clock):
        """Bind the standing authority to this original broker intent; never create a grant."""
        try:
            origin = json.loads(manifest.get("source", ""))
        except (ValueError, TypeError):
            origin = {}
        ref = origin.get("automatic_completion_policy_sha256") if isinstance(origin, dict) else None
        if ref is None:
            return None
        policy = self._automatic_completion_policy(clock, manifest["strategy_id"])
        saved, state = self._get("best_plan", {}), self._get("best_execution", {})
        plan, meta = saved.get("plan", {}), saved.get("metadata", {})
        opening, closing = timestamp(meta["next_open_utc"]), timestamp(meta["next_close_utc"])
        end = closing - timedelta(seconds=600)
        from zoneinfo import ZoneInfo
        day = clock.astimezone(ZoneInfo("America/New_York")).date().isoformat()
        targets = state.get("target_quantities", {})
        if (policy is None or ref != _first_execution_sha(policy)
                or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or manifest["provenance"] != "live" or manifest["strategy_id"] != "HGB_DIAG_5"
                or origin.get("automatic_completion_plan_sha256") != _first_execution_sha(plan)
                or origin.get("automatic_completion_source_refs_sha256") != _first_execution_sha(meta.get("source_refs"))
                or origin.get("signal_date") != meta.get("signal_date")
                or origin.get("execution_date") != meta.get("execution_date") or day != meta.get("execution_date")
                or not "2026-01-01" <= meta["signal_date"] < day < policy["evaluation_end_exclusive"]
                or origin.get("next_open_utc") != meta.get("next_open_utc")
                or origin.get("next_close_utc") != meta.get("next_close_utc")
                or origin.get("signal_close_utc") != meta.get("signal_close_utc")
                or origin.get("budget") != policy["broker_budget"]
                or origin.get("execution_delay_minutes") != 0
                or origin.get("execution_window_seconds") != 600
                or not opening <= clock < end or timestamp(manifest["expires_at"]) != end
                or state.get("signal_date") != meta["signal_date"] or state.get("phase") != origin.get("phase")
                or state.get("manifest") != manifest or origin.get("phase") not in {"SELL", "BUY"}
                or state.get("automatic_completion_policy_sha256") != ref
                or any(t["code"] not in targets or t["target_qty"] > targets[t["code"]]
                       or (origin["phase"] == "SELL" and t["target_qty"] != targets[t["code"]])
                       for t in manifest["targets"])):
            raise ValueError("AUTOMATIC_COMPLETION_BROKER_INTENT_CHANGED_OR_EXPIRED")
        return policy

    def _terminal_retry_remaining(self, code, side, opening, closing, strategy_id):
        """Native original quantity less cumulative actual fills is the only retry cap."""
        rows = list(self.db.execute("SELECT o.qty,o.status,f.payload FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
            "WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=? AND o.code=? "
            "AND o.side=? AND o.status!='CANCELLED_BEFORE_SEND' AND o.created_at>=? AND o.created_at<? ORDER BY o.created_at,o.rowid",
            (strategy_id, self.account_id, code, side, timestamp(opening).isoformat(), timestamp(closing).isoformat())))
        filled = 0
        if not rows:
            raise ValueError("TERMINAL_RETRY_NATIVE_TERMINAL_FILL_MISSING")
        for quantity, status, payload in rows:
            evidence = json.loads(payload) if payload else {}
            qty = evidence.get("fill_qty")
            if (status not in {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                    or evidence.get("fill_source") != "MOOMOO_SIMULATE_ORDER_RECONCILE"
                    or type(qty) is not int or not 0 <= qty <= quantity
                    or (qty and (not isinstance(evidence.get("fill_price"), (float, int))
                        or evidence["fill_price"] <= 0))):
                raise ValueError("TERMINAL_RETRY_NATIVE_TERMINAL_FILL_MISSING")
            filled += qty
        remaining = rows[0][0] - filled
        if remaining < 0:
            raise ValueError("TERMINAL_RETRY_NATIVE_FILL_EXCEEDS_ORIGINAL")
        return remaining

    def _validate_published_manual_completion(self, manifest, clock):
        try:
            origin = json.loads(manifest.get("source", "{}"))
        except (TypeError,ValueError):
            origin = {}
        if not isinstance(origin,dict):
            origin = {}
        validator = getattr(self, "published_target_manual_validator", None)
        if callable(validator):
            return validator(manifest, clock)
        if origin.get("published_target_manual_completion_sha256") is not None:
            raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_OWNER_REQUIRED")
        return None

    def _plan(self, *, allow_partial_quotes=False):
        if self.paper_only:
            raise ValueError("独立纸面策略仅通过下一合法开盘的cohort执行")
        manifest = self._manifest()
        if type(allow_partial_quotes) is not bool:
            raise ValueError("部分报价执行选项必须为布尔值")
        try:
            origin = json.loads(manifest.get("source", ""))
        except (ValueError, TypeError):
            origin = None
        if allow_partial_quotes:
            if (self.mode != "moomoo_simulate" or not isinstance(origin, dict)
                    or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"):
                raise ValueError("部分报价执行仅允许已授权的模拟盘执行计划")
        reset_id = origin.get("reset_id") if isinstance(origin, dict) else None
        if reset_id is not None:
            reset = self._get("best_full_liquidation_reset", None)
            if (self.mode != "moomoo_simulate" or manifest["strategy_id"] != "HGB_DIAG_5"
                    or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                    or not isinstance(reset, dict) or reset.get("reset_id") != reset_id
                    or reset.get("account_id") != self.account_id
                    or reset.get("signal_date") != origin.get("signal_date")
                    or origin.get("phase") not in {"SELL", "BUY"}):
                raise ValueError("SIMULATE_RESET_ORDER_IDENTITY_MISMATCH")
            saved = self._get("best_plan", {})
            frozen_plan, frozen_metadata = saved.get("plan", {}), saved.get("metadata", {})
            fingerprint = lambda value: hashlib.sha256(json.dumps(
                value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
            expected_source = frozen_plan.get("source_hash") or hashlib.sha256(json.dumps(
                frozen_plan.get("source_refs", frozen_metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest()
            capital = self._get("best_capital", {})
            if (fingerprint(frozen_plan) != reset.get("plan_sha256")
                    or fingerprint(frozen_metadata) != reset.get("metadata_sha256")
                    or origin.get("source_hash") != expected_source
                    or origin.get("next_open_utc") != frozen_metadata.get("next_open_utc")
                    or origin.get("signal_close_utc") != frozen_metadata.get("signal_close_utc")
                    or origin.get("budget") != capital.get("budget")
                    or capital.get("account_id") != self.account_id
                    or capital.get("unused_cash") != reset.get("unused_cash")):
                raise ValueError("SIMULATE_RESET_ORDER_SOURCE_BINDING_CHANGED")
            baseline = reset.get("post_liquidation_baseline")
            if origin["phase"] == "SELL":
                if (reset.get("stage") != "ARMED" or baseline is not None
                        or any(target["target_qty"] != 0 for target in manifest["targets"])):
                    raise ValueError("SIMULATE_RESET_SELL_REQUIRES_UNFINISHED_FULL_LIQUIDATION")
            elif (reset.get("stage") != "REBUYING" or not isinstance(baseline, dict)
                    or baseline.get("reset_id") != reset_id or baseline.get("account_id") != self.account_id
                    or baseline.get("valuation_basis") != "ACTUAL_POST_LIQUIDATION_CASH"
                    or baseline.get("positions") != {}):
                raise ValueError("SIMULATE_RESET_BUY_REQUIRES_CONFIRMED_LIQUIDATION")
            elif (number(baseline.get("cash"), "真实清仓现金", .000001) != baseline.get("equity")
                    or timestamp(baseline.get("asof")) > datetime.now(timezone.utc)):
                raise ValueError("SIMULATE_RESET_ACTUAL_CASH_BASELINE_INVALID")
        self._validate_first_execution_manifest(manifest, datetime.now(timezone.utc))
        self._validate_published_manual_completion(manifest, datetime.now(timezone.utc))
        manual_sell = self._manual_residual_sell_permission(manifest, datetime.now(timezone.utc))
        automatic_policy = self._automatic_broker_completion(manifest, datetime.now(timezone.utc))
        if automatic_policy is not None and not allow_partial_quotes:
            raise ValueError("AUTOMATIC_COMPLETION_PARTIAL_EXECUTION_REQUIRED")
        if manual_sell is not None and not allow_partial_quotes:
            raise ValueError("人工剩余卖出必须通过原逐票安全执行入口")
        retry_generations = origin.get("retry_generations", {}) if allow_partial_quotes else {}
        generation_limit = self.limits["max_orders_per_day"] if automatic_policy is not None else 5
        if (not isinstance(retry_generations, dict) or any(
                not isinstance(code, str) or type(generation) is not int
                or not 0 <= generation <= generation_limit
                for code, generation in retry_generations.items())):
            raise ValueError("模拟盘重试代次无效")
        reasons = execution_reasons(manifest, self.mode, self.limits["max_signal_age_seconds"])
        if self.halt_event.is_set():
            reasons.append("紧急停止已锁定：" + self.halt_reason)
        if self._pending():
            reasons.append("存在未完成或未知的模拟订单，请先对账")
        snap = self._snapshot([t["code"] for t in manifest["targets"]],
                              allow_partial_quotes=allow_partial_quotes)
        self.account = snap
        cash, equity = number(snap["cash"], "现金"), number(snap["equity"], "权益", .01)
        if snap["open_orders"]:
            reasons.append("模拟账户存在未完成订单，先等待成交或在 Moomoo 撤单")
        day = datetime.now(timezone.utc).date().isoformat()
        baseline_key = self.mode + ":" + self.account_id
        self.db.execute("INSERT OR IGNORE INTO baselines VALUES (?,?,?)", (day, baseline_key, equity))
        self.db.commit()
        baseline = self.db.execute("SELECT equity FROM baselines WHERE day=? AND account=?", (day, baseline_key)).fetchone()[0]
        if baseline - equity >= self.limits["max_daily_loss"]:
            self._halt("当日首次观测权益以来的亏损触发限额")
            reasons.append(self.halt_reason)
        existing = list(self.db.execute("SELECT * FROM orders WHERE created_at LIKE ? AND mode=? AND account_id=?", (day + "%", self.mode, self.account_id)))
        if allow_partial_quotes:
            existing = [row for row in existing if row["status"] != "CANCELLED_BEFORE_SEND"]
        turnover = sum(r["qty"] * r["limit_price"] for r in existing)
        exposure = 0.0
        positions = snap["positions"]
        for code, pos in positions.items():
            number(pos["qty"], "持仓数量")
            number(pos["sellable"], "可卖数量")
            exposure += number(pos["market_value"], "持仓市值")
        orders, skipped = [], []
        reserved_cash = cash
        for target in manifest["targets"]:
            code = target["code"]
            pos = positions.get(code, dict(qty=0, sellable=0, market_value=0))
            delta = target["target_qty"] - pos["qty"]
            if delta == 0:
                continue
            if automatic_policy is not None and ((origin["phase"] == "SELL" and delta > 0)
                    or (origin["phase"] == "BUY" and delta < 0)):
                raise ValueError("AUTOMATIC_COMPLETION_ORDER_DIRECTION_CHANGED")
            if manual_sell is not None and (code != manual_sell["code"] or delta > 0 or -delta > manual_sell["max_sell_qty"]):
                raise ValueError("MANUAL_RESIDUAL_SELL_FIXED_TARGET_OR_MAX_QUANTITY_CHANGED")
            if reset_id is not None and ((origin["phase"] == "SELL" and delta > 0)
                    or (origin["phase"] == "BUY" and delta < 0)):
                reasons.append(code + " 重启委托方向与已确认阶段不一致")
                continue
            if int(delta) != delta:
                reason = code + " 持仓含小数股，首版不支持"
                if allow_partial_quotes:
                    skipped.append(dict(code=code, reason=reason))
                else:
                    reasons.append(reason)
                continue
            generation = retry_generations.get(code, 0)
            if generation:
                previous_attempts = [row for row in self.db.execute(
                    "SELECT created_at,status FROM orders WHERE strategy_id=? AND mode=? AND account_id=? AND code=? AND side=?",
                    (manifest["strategy_id"], self.mode, self.account_id, code, "BUY" if delta > 0 else "SELL"))
                    if timestamp(row["created_at"]) >= timestamp(origin["next_open_utc"])
                    and row["status"] != "CANCELLED_BEFORE_SEND"]
                if (len(previous_attempts) != generation or any(
                        row["status"] not in {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                        for row in previous_attempts)):
                    reasons.append(code + " 重试前原订单尚未确认失败或代次不一致")
                    continue
                if automatic_policy is not None:
                    remaining = self._terminal_retry_remaining(code, "BUY" if delta > 0 else "SELL", origin["next_open_utc"],
                        origin["next_close_utc"], manifest["strategy_id"])
                    if abs(delta) > remaining:
                        reasons.append(code + " SELL重试超过原单减实际成交后的差额")
                        continue
            identity_parts = [self.mode, self.account_id, manifest["strategy_id"], manifest["asof"], code]
            if reset_id is not None:
                identity_parts.extend(["reset", reset_id, origin["phase"]])
            if generation:
                identity_parts.append(generation)
            identity = json.dumps(identity_parts)
            key = hashlib.sha256(identity.encode()).hexdigest()[:32]
            processed_order = self.db.execute("SELECT status FROM orders WHERE id=?", (key,)).fetchone()
            if allow_partial_quotes and processed_order and processed_order["status"] != "CANCELLED_BEFORE_SEND":
                skipped.append(dict(code=code, reason="此信号已经处理，不自动重发", already_processed=True))
                continue
            quote_error = snap.get("quote_errors", {}).get(code)
            if allow_partial_quotes and quote_error:
                skipped.append(dict(code=code, reason=str(quote_error)))
                continue
            q = snap["quotes"].get(code)
            if not q:
                reason = code + " 缺少行情（本地演示仅支持 AAPL/MSFT/SPY）"
                if allow_partial_quotes:
                    skipped.append(dict(code=code, reason=reason))
                else:
                    reasons.append(reason)
                continue
            try:
                p, bid, ask = [number(q[k], code + " " + k, .000001) for k in ("price", "bid", "ask")]
                tick = number(q["price_tick"], "最小价位", .000001)
                lot = number(q["lot_size"], "交易单位", 1)
                if int(lot) != lot or abs(delta) % lot:
                    raise ValueError("数量不满足整手交易单位")
                age = (datetime.now(timezone.utc) - timestamp(q["asof"])).total_seconds()
                max_age = min(self.limits["max_quote_age_seconds"], 30) if allow_partial_quotes else self.limits["max_quote_age_seconds"]
                min_age = 0 if allow_partial_quotes else -2
                if age < min_age or age > max_age:
                    raise ValueError("行情过期或时间来自未来")
                if q["tradable"] is not True:
                    raise ValueError("非正常交易时段、停牌或证券不可交易")
                max_spread = (manual_sell["max_spread_bps"] if manual_sell is not None
                    else min(self.limits["max_spread_bps"], 50) if allow_partial_quotes else self.limits["max_spread_bps"])
                spread_ok = (auto_completion_spread_is_valid(q) if automatic_policy is not None
                    and automatic_policy["one_tick_spread"] and manual_sell is None
                    else ask >= bid and (ask - bid) / ((ask + bid) / 2) * 10000 <= max_spread)
                if not spread_ok:
                    raise ValueError("买卖价差异常")
                if abs((ask if delta > 0 else bid) / p - 1) > .02:
                    raise ValueError("限价偏离最近成交价超过2%")
            except (ValueError, KeyError, TypeError) as exc:
                reason = code + "：" + str(exc)
                if allow_partial_quotes:
                    skipped.append(dict(code=code, reason=reason))
                else:
                    reasons.append(reason)
                continue
            side = "BUY" if delta > 0 else "SELL"
            rounding = ROUND_CEILING if delta > 0 else ROUND_FLOOR
            limit = float((Decimal(str(ask if delta > 0 else bid)) / Decimal(str(tick))).to_integral_value(rounding=rounding) * Decimal(str(tick)))
            if manual_sell is not None:
                if bid < manual_sell["limit_price"] or Decimal(str(bid)) % Decimal(str(tick)):
                    skipped.append(dict(code=code, reason="新鲜买一低于人工最低限价或不符最小价位；未发送"))
                    continue
                limit = float(bid)
            if limit <= 0 or abs(limit / p - 1) > .02:
                reason = code + " 最终限价无效或取整后偏离最近成交价超过2%"
                if allow_partial_quotes:
                    skipped.append(dict(code=code, reason=reason))
                else:
                    reasons.append(reason)
                continue
            qty = abs(int(delta))
            notional = qty * limit
            if processed_order and not (allow_partial_quotes and processed_order["status"] == "CANCELLED_BEFORE_SEND"):
                reasons.append(code + " 此信号已经处理，不自动重发")
            if notional > self.limits["max_order_notional"]:
                reasons.append(code + " 超过单笔金额上限")
            projected = target["target_qty"] * max(limit, p)
            # Breached holdings may be reduced, never increased further.
            if delta > 0 and projected > self.limits["max_position_notional"]:
                reasons.append(code + " 超过单标的持仓上限")
            if delta < 0 and qty > pos["sellable"]:
                reasons.append(code + " 超过可卖数量，禁止裸卖")
            if delta > 0:
                reserved_cash -= notional * 1.005  # 0.5% fee reserve; no sell proceeds financing buys.
                exposure += notional
            turnover += notional
            orders.append(dict(id=key, code=code, side=side, qty=qty, limit_price=limit, notional=round(notional, 4)))
        if reserved_cash < self.limits["min_cash_reserve"] and any(o["side"] == "BUY" for o in orders):
            reasons.append("买入后现金不足保留额（含0.5%费用缓冲；不使用融资购买力）")
        if exposure > self.limits["max_total_exposure"] and any(o["side"] == "BUY" for o in orders):
            reasons.append("超过组合总敞口上限；卖出未成交前不释放额度")
        if turnover > self.limits["max_daily_turnover"]:
            reasons.append("超过每日总交易金额上限")
        if len(existing) + len(orders) > self.limits["max_orders_per_day"]:
            reasons.append("超过每日订单数上限")
        return dict(allowed=not reasons, reasons=list(dict.fromkeys(reasons)), orders=orders,
            skipped=skipped, allow_partial_quotes=allow_partial_quotes,
            account=snap, created_at=now_iso(), quote_source="synthetic" if self.mode == "paper" else "moomoo")

    def preview(self, *, allow_partial_quotes=False):
        with self.lock:
            try:
                self.preview_result = self._plan(allow_partial_quotes=allow_partial_quotes)
                self.last_error = ""
                return self.preview_result
            except Exception as exc:
                self.preview_result = None
                self.last_error = str(exc)
                raise

    def step(self, automatic=False, *, respect_cancel=False, allow_partial_quotes=False,
             broker_order_type="NORMAL"):
        with self.lock:
            if broker_order_type not in {"NORMAL", "MARKET"}:
                raise ValueError("模拟委托类型无效")
            if broker_order_type == "MARKET" and self.mode != "moomoo_simulate":
                raise ValueError("市价单仅可发送至已选择的 MOOMOO 模拟账户")
            if not automatic:
                self._require_stopped()
            if respect_cancel and self.cancel_step.is_set():
                raise ValueError("执行前已收到停止请求")
            if not respect_cancel:
                self.cancel_step.clear()
            if self.halt_event.is_set():
                raise ValueError("紧急停止已锁定")
            manual_gate = self._manual_residual_sell_permission(self._manifest(), datetime.now(timezone.utc))
            if manual_gate is not None and broker_order_type != "NORMAL":
                raise ValueError("MANUAL_RESIDUAL_SELL_NORMAL_ONLY")
            plan = self.preview(allow_partial_quotes=allow_partial_quotes)
            if not plan["allowed"]:
                self._audit("BLOCKED", "；".join(plan["reasons"]))
                raise ValueError("；".join(plan["reasons"]))
            submitted = []
            for item in plan["orders"]:
                if self.halt_event.is_set() or self.cancel_step.is_set() or (automatic and self.stop_event.is_set()):
                    break
                # Rebuild from fresh account + quotes before every submission.
                fresh = self._plan(allow_partial_quotes=allow_partial_quotes)
                if not fresh["allowed"]:
                    if submitted:
                        break
                    raise ValueError("；".join(fresh["reasons"]))
                order = next((o for o in fresh["orders"] if o["id"] == item["id"]), None)
                if not order:
                    if allow_partial_quotes:
                        plan["skipped"].extend(row for row in fresh["skipped"]
                            if row["code"] == item["code"] and row not in plan["skipped"])
                    continue
                if self.halt_event.is_set() or self.cancel_step.is_set() or (automatic and self.stop_event.is_set()):
                    break
                self._validate_first_execution_manifest(self._manifest(), datetime.now(timezone.utc))
                self._validate_published_manual_completion(self._manifest(), datetime.now(timezone.utc))
                self._automatic_broker_completion(self._manifest(), datetime.now(timezone.utc))
                previous = self.db.execute("SELECT status FROM orders WHERE id=?", (order["id"],)).fetchone()
                if allow_partial_quotes and previous and previous["status"] == "CANCELLED_BEFORE_SEND":
                    self.db.execute("UPDATE orders SET created_at=?,status='SUBMITTING',qty=?,limit_price=?,order_id=NULL,order_type=? WHERE id=? AND status='CANCELLED_BEFORE_SEND'",
                        (now_iso(), order["qty"], order["limit_price"], broker_order_type, order["id"]))
                    self._audit("RETRY_DEFINITELY_UNSENT", order["code"] + "；原意图未送券商，仅在当前有效窗口重试")
                else:
                    self.db.execute("INSERT INTO orders(id,created_at,strategy_id,mode,account_id,code,side,qty,limit_price,status,order_id,order_type) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (order["id"], now_iso(), self.active, self.mode, self.account_id, order["code"], order["side"], order["qty"], order["limit_price"], "SUBMITTING", None, broker_order_type))
                self.db.commit()  # durable intent BEFORE network side effect
                if self.halt_event.is_set() or self.cancel_step.is_set() or (automatic and self.stop_event.is_set()):
                    self.db.execute("UPDATE orders SET status='CANCELLED_BEFORE_SEND' WHERE id=?", (order["id"],))
                    self.db.commit()
                    self._audit("CANCELLED_BEFORE_SEND", "本地意图已记录，但因暂停而未发送")
                    break
                try:
                    if self.mode == "paper":
                        ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
                        sign = 1 if order["side"] == "BUY" else -1
                        ledger["cash"] -= sign * order["notional"] + order["notional"] * .001
                        ledger["positions"][order["code"]] = ledger["positions"].get(order["code"], 0) + sign * order["qty"]
                        result = dict(status="FILLED", order_id="paper-" + order["id"])
                        # Ledger and completed order commit in one transaction.
                        self.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("paper", json.dumps(ledger)))
                    else:
                        submission_options = dict(allow_partial_quotes=True,
                            execution_deadline_utc=self._manifest()["expires_at"]) if allow_partial_quotes else {}
                        self._validate_published_manual_completion(self._manifest(), datetime.now(timezone.utc))
                        manual_sell = self._manual_residual_sell_permission(self._manifest(), datetime.now(timezone.utc))
                        automatic_policy = self._automatic_broker_completion(self._manifest(), datetime.now(timezone.utc))
                        if automatic_policy is not None and automatic_policy["one_tick_spread"] and manual_sell is None:
                            submission_options["allow_single_tick_spread"] = True
                        if manual_sell is not None:
                            if broker_order_type != "NORMAL" or order["code"] != manual_sell["code"] or order["side"] != "SELL":
                                raise ValueError("MANUAL_RESIDUAL_SELL_NORMAL_ONLY")
                            submission_options["single_sell_spread_bps"] = manual_sell["max_spread_bps"]
                        if broker_order_type == "MARKET":
                            submission_options["order_type"] = "MARKET"
                        result = self.broker.submit({k: order[k] for k in ("code", "side", "qty", "limit_price")},
                            order["id"], **submission_options)
                        if not result.get("order_id"):
                            raise ValueError("券商未返回可核对的订单号")
                        # Broker accepting a request does not establish a fill.
                        result["status"] = "PENDING_RECONCILE"
                    self.db.execute("UPDATE orders SET status=?,order_id=? WHERE id=?", (result["status"], str(result["order_id"]), order["id"]))
                    self.db.commit()
                    submitted.append(order)
                    self._audit("SUBMIT", f"{self.mode} {order['code']} {order['side']} {order['qty']} {result['status']}")
                except Exception as exc:
                    from .brokers import BrokerOrderNotSent
                    if isinstance(exc, BrokerOrderNotSent):
                        self.db.rollback()
                        self.db.execute("UPDATE orders SET status='CANCELLED_BEFORE_SEND' WHERE id=?", (order["id"],))
                        self.db.commit()
                        plan["skipped"].append(dict(code=order["code"], reason=str(exc),
                            definitely_not_sent=True, retry_after_seconds=getattr(exc, "retry_after_seconds", 0)))
                        self._audit("CANCELLED_BEFORE_SEND", order["code"] + ": " + str(exc))
                        break
                    self.db.rollback()
                    self.db.execute("UPDATE orders SET status='UNKNOWN' WHERE id=?", (order["id"],))
                    self.db.commit()
                    self._halt("提交结果未知，已禁止重试；请在模拟账户对账后处理")
                    raise
                if self.mode == "moomoo_simulate":
                    # One broker order per cycle; reconcile before further work.
                    break
            if (not self.halt_event.is_set() and not self.cancel_step.is_set()
                    and not (self.mode == "moomoo_simulate" and submitted and self._pending())):
                self.account = self._snapshot([t["code"] for t in self._manifest()["targets"]],
                                              allow_partial_quotes=allow_partial_quotes)
            self.preview_result = None
            message = "本地纸面成交" if self.mode == "paper" else "已发往 Moomoo 模拟账户；需对账确认成交"
            if allow_partial_quotes and not submitted:
                message = "本轮未送出模拟订单；逐证券原因已记录"
            return {"submitted": submitted, "skipped": plan["skipped"], "message": message}

    def reconcile(self):
        with self.lock:
            if self.mode != "moomoo_simulate" or not self.broker:
                raise ValueError("先选择原 Moomoo 模拟账户")
            results = []
            for row in self._pending():
                if row["account_id"] != self.account_id:
                    raise ValueError("未完成订单不属于当前模拟账户")
                result = self.broker.reconcile(row["id"], row["order_id"])
                reported_type = result.get("order_type")
                if reported_type is not None and reported_type != row["order_type"]:
                    result = {"status": "UNKNOWN", "order_id": row["order_id"],
                              "dealt_qty": 0, "dealt_avg_price": None}
                status = result.get("status", "UNKNOWN")
                fill = None
                dealt = result.get("dealt_qty")
                if (status in {"FILLED_ALL", "FILLED_PART", "CANCELLED_PART", "FILLED"}
                        or (status in {"FAILED", "CANCELLED_ALL"} and dealt == 0)) and type(dealt) in (int, float):
                    number(dealt, "券商实际成交数量")
                    if int(dealt) != dealt or dealt > row["qty"]:
                        self.db.rollback()
                        raise ValueError("券商实际成交数量与订单不一致")
                    avg = result.get("dealt_avg_price")
                    price = number(avg, "券商实际成交均价", 1e-12) if avg is not None and dealt else None
                    real_time = result.get("filled_at")
                    observed = timestamp(real_time).isoformat() if real_time else now_iso()
                    fill = dict(fill_qty=int(dealt), fill_price=price, filled_at=observed,
                        fill_time_basis="BROKER" if real_time else "RECONCILE_OBSERVED",
                        fill_source="MOOMOO_SIMULATE_ORDER_RECONCILE", fee=None)
                self.db.execute("UPDATE orders SET status=?,order_id=? WHERE id=?", (status, result.get("order_id") or row["order_id"], row["id"]))
                if fill is not None:
                    self.db.execute("INSERT OR REPLACE INTO order_fills VALUES (?,?)", (row["id"], json.dumps(fill)))
                self.db.commit()
                results.append(result)
            self._audit("RECONCILE", json.dumps(results, ensure_ascii=False))
            self.preview_result = None
            return results

    def start(self):
        with self.lock:
            self._require_stopped()
            plan = self.preview()
            if not plan["allowed"]:
                raise ValueError("；".join(plan["reasons"]))
            self.stop_event.clear()
            self.worker = threading.Thread(target=self._run, daemon=True, name="simulation-runner")
            self.worker.start()
            self._audit("START", "每30秒检查目标；任何错误自动停止；进程重启不恢复自动执行")

    def _run(self):
        while not self.stop_event.is_set():
            try:
                if self.mode == "moomoo_simulate" and self._pending():
                    self.reconcile()
                    with self.lock:
                        if self._pending():
                            self.stop_event.set()
                            self.last_error = "模拟订单尚未完成，已暂停；请对账"
                            break
                self.step(automatic=True)
            except Exception as exc:
                with self.lock:
                    self.last_error = str(exc)
                    self.stop_event.set()
                    self._audit("AUTO_STOP", self.last_error)
                break
            if self.stop_event.wait(30):
                break

    def order_snapshot(self, *, account_id=None):
        """Read bounded presentation orders without unrelated strategy/audit decode."""
        with self.lock:
            if account_id is None:
                recent = [dict(row) for row in self.db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100")]
            else:
                recent = [dict(row) for row in self.db.execute("SELECT * FROM orders WHERE account_id=? "
                    "AND mode='moomoo_simulate' ORDER BY created_at DESC LIMIT 100", (account_id,))]
            ids = tuple(row["id"] for row in recent)
            fills = {row[0]: json.loads(row[1]) for row in self.db.execute(
                "SELECT id,payload FROM order_fills WHERE id IN ("+",".join("?" for _ in ids)+")",ids)} if ids else {}
            orders = [{**row, **fills.get(row["id"], {})} for row in recent]
            if account_id is not None:
                orders = [{**merged,"id":row["id"],"account_id":row["account_id"]} for row,merged in zip(recent,orders)]
            return dict(account_id=self.account_id, orders=orders)

    def state(self):
        with self.lock:
            snapshot = self.order_snapshot()
            return dict(mode=self.mode, account_id=snapshot["account_id"], running=not self.stop_event.is_set(), halted=self.halt_event.is_set(),
                halt_reason=self.halt_reason, active_strategy=self.active,
                strategies=[json.loads(r[0]) for r in self.db.execute("SELECT payload FROM strategies ORDER BY id")],
                limits=self.limits, connection=self.connection, account=self.account,
                orders=snapshot["orders"],
                audit=[dict(r) for r in self.db.execute("SELECT * FROM audit ORDER BY rowid DESC LIMIT 100")],
                preview=self.preview_result, last_error=self.last_error, live_enabled=False)

    def close(self):
        self.stop_event.set()
        if self.worker:
            self.worker.join(timeout=5)
        with self.lock:
            if self.broker:
                self.broker.close()
            self.db.close()
            self.data_lock.close()
