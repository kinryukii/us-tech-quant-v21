"""Persistent, fail-closed execution engine. No live trading path exists."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json
from pathlib import Path
import sqlite3
import threading

from .strategy import code_valid, execution_reasons, now_iso, number, timestamp, validate_manifest
from .locking import DataLock

DEFAULT_LIMITS = dict(max_order_notional=1000, max_daily_turnover=5000,
    max_position_notional=2000, max_total_exposure=5000, min_cash_reserve=1000,
    max_daily_loss=200, max_orders_per_day=20, max_quote_age_seconds=60,
    max_spread_bps=50, max_signal_age_seconds=86400)
TERMINAL = {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED", "FILLED", "CANCELLED_BEFORE_SEND"}


class Engine:
    def __init__(self, data_dir, broker_factory=None, *, quote_provider=None,
                 paper_account_id="paper", paper_only=False):
        self.path = Path(data_dir)
        self.path.mkdir(parents=True, exist_ok=True)
        self.data_lock = DataLock(self.path / "engine.lock")
        self.lock = threading.RLock()
        self.halt_event = threading.Event()
        self.stop_event = threading.Event()
        self.cancel_step = threading.Event()
        self.stop_event.set()
        self.db = sqlite3.connect(self.path / "state.sqlite3", check_same_thread=False)
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
            if inception is None:
                inception = now_iso()
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

    def paper_mark(self, quotes, *, day=None, basis="MOOMOO_REALTIME"):
        """Persist observed marks; callers supply real quotes or verified exact-date closes."""
        with self.lock:
            if self.mode != "paper":
                raise ValueError("只允许标记本地纸面账本")
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}})
            marks = self._get("paper_marks", {})
            for code, quote in quotes.items():
                if code not in ledger["positions"] or not ledger["positions"][code]:
                    continue
                price = number(quote["price"], "真实标价", minimum=1e-12)
                asof = timestamp(quote["asof"]).isoformat()
                old = marks.get(code)
                if old and timestamp(old["asof"]) > timestamp(asof):
                    continue  # A prior close must never overwrite a newer live mark.
                marks[code] = dict(price=price, asof=asof, source=quote.get("source", "UNKNOWN"), basis=basis)
            self._set("paper_marks", marks)
            book = self.paper_book()
            self._observe_paper_equity(book["equity"], max((q["asof"] for q in marks.values()), default=None))
            book["max_drawdown_fraction"] = self._get("paper_metrics", {"max_drawdown_fraction": 0.0})["max_drawdown_fraction"]
            if day is not None and book["equity"] is not None and (
                    self.paper_inception_date is None or day >= self.paper_inception_date):
                payload = dict(date=day, cash=book["cash"], equity=book["equity"],
                    nav=book["equity"] / 10000.0, fees=book["fees"], basis=basis,
                    asof=max((q["asof"] for q in marks.values()), default=None),
                    sources=sorted({q["source"] for q in marks.values()}), paper=True)
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

    def paper_rebalance(self, strategy_id, plan, quotes, *, now, next_open_utc,
                        signal_date, execution_date, signal_close_utc, source_refs=None,
                        fee_bps=5, allow_partial_quotes=False, quote_errors=None,
                        execution_window_seconds=60):
        """Atomic local fills for one calendar-gated cohort signal. No broker methods exist here.

        The frozen weights remain in the batch record. Integer shares use the observed
        bid/ask; sales settle before purchases, and each purchase reserves its actual fee.
        This route deliberately does not inherit the manual demo's exposure/order caps.
        """
        with self.lock:
            if not self.paper_only or self.mode != "paper" or self.broker is not None:
                raise ValueError("独立策略执行仅允许永久纸面账户")
            if self.halt_event.is_set() or self.cancel_step.is_set():
                raise ValueError("纸面账户已停止或锁定")
            clock = timestamp(now.isoformat()) if isinstance(now, datetime) else timestamp(now)
            opening, closing = timestamp(next_open_utc), timestamp(signal_close_utc)
            if type(allow_partial_quotes) is not bool:
                raise ValueError("部分报价执行选项必须为布尔值")
            if type(execution_window_seconds) is not int or not 1 <= execution_window_seconds <= 600:
                raise ValueError("计划执行窗口必须为1至600秒整数")
            if closing >= opening or closing > clock or not opening <= clock < opening + timedelta(seconds=execution_window_seconds):
                raise ValueError("MISSED_OPEN_OR_INVALID_SIGNAL_CLOCK")
            if signal_date >= execution_date or plan.get("source_date", signal_date) != signal_date:
                raise ValueError("信号日和执行日不一致")
            if type(fee_bps) not in (int, float) or fee_bps != 5:
                raise ValueError("冻结纸面费用假设固定为单边5bp")
            fee_rate = .0005
            batch_id = hashlib.sha256(json.dumps([self.paper_account_id, strategy_id, signal_date,
                execution_date], separators=(",", ":")).encode()).hexdigest()
            existing = self.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
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
            target_cash = number(plan["target_cash_weight"], "目标现金权重")
            if abs(sum(weights.values()) + target_cash - 1) > 1e-8:
                raise ValueError("目标权重和现金不归一")
            if allow_partial_quotes:
                return self._paper_partial_rebalance(strategy_id, plan, quotes,
                    quote_errors=quote_errors, clock=clock, opening=opening,
                    signal_date=signal_date, execution_date=execution_date,
                    source_refs=source_refs or {}, weights=weights, target_cash=target_cash,
                    batch_id=batch_id, existing=json.loads(existing[0]) if existing else None)
            ledger = self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0})
            holdings = dict(ledger["positions"])
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
            target_cash, batch_id, existing):
        """Commit qualified symbols only; unqualified allocations remain unspent.

        Each symbol receives at most one decision for this frozen signal. Failed
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
        ledger = self._get("paper", {"cash": 10000.0, "positions": {}, "fees": 0.0})
        holdings = dict(ledger["positions"])
        if any(not code_valid(code) or type(qty) is not int or qty < 0 for code, qty in holdings.items()):
            raise ValueError("独立纸面账本必须为有效美股代码和非负整数股")
        required = set(old.get("required_codes", [])) | {c for c, w in weights.items() if w}
        required.update(c for c, qty in holdings.items() if qty)
        processed = set(old.get("processed_codes", []))
        pending = required - processed
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
                if bid > ask or (ask - bid) / price * 10000 > 50:
                    raise ValueError("真实盘口价差无效（上限50bp）")
                if quote.get("lot_size", 1) != 1:
                    raise ValueError("仅支持美股整数股")
                validated[code] = dict(price=price, bid=bid, ask=ask,
                    asof=asof.isoformat(), source=quote.get("source", "MOOMOO_OPEND"))
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
        for code in sorted(pending):
            if code not in validated:
                continue
            if equity is None and weights.get(code, 0):
                failures[code] = "账户下单权益未能完整核验；缺少持仓真实标价: " + ", ".join(missing_marks)
                continue
            desired[code] = 0 if not weights.get(code, 0) else int((
                Decimal(str(weights[code])) * Decimal(str(equity)) /
                Decimal(str(validated[code]["ask"]))).to_integral_value(rounding=ROUND_FLOOR))
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
                key = hashlib.sha256((batch_id + ":" + code).encode()).hexdigest()[:32]
                fills.append(dict(id=key, strategy_id=strategy_id, account_id=self.paper_account_id,
                    mode="paper", paper=True, code=code, ticker=code.removeprefix("US."), side=side,
                    qty=qty, fill_price=price, limit_price=price, notional=notional, fee=fee,
                    fee_bps=5, filled_at=clock.isoformat(), signal_date=signal_date,
                    execution_date=execution_date, quote_asof=quote["asof"], source=quote["source"],
                    signal_source_refs=source_refs, source_plan_sha256=plan_hash,
                    order_status="FILLED", status="FILLED", order_id="paper-" + key, sequence=len(fills)))
                filled_codes.add(code)
        for code in sorted(desired):
            processed.add(code)
            decisions.append(dict(code=code, at=clock.isoformat(), target_qty=desired[code],
                qty_before=original_holdings.get(code, 0), qty_after=holdings.get(code, 0),
                reason="FILLED" if any(fill["code"] == code for fill in fills) else (
                    "TARGET_SATISFIED" if original_holdings.get(code, 0) == desired[code] else "CASH_CONSTRAINT")))
            failures.pop(code, None)
        skipped = [dict(code=code, reason=failures.get(code, "真实行情缺失"))
                   for code in sorted(required - processed)]
        status = "EXECUTED" if not skipped else "PARTIALLY_EXECUTED" if processed else "WAITING_QUOTES"
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
        if self.halt_event.is_set() or self.cancel_step.is_set():
            raise ValueError("纸面成交前已收到停止请求")
        updated = dict(cash=max(0, cash), positions={c: q for c, q in holdings.items() if q}, fees=fees)
        try:
            self.db.execute("BEGIN IMMEDIATE")
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

    def paper_trades(self, limit=None):
        with self.lock:
            if limit is None:
                return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM paper_fills ORDER BY rowid")]
            if type(limit) is not int or limit < 1:
                raise ValueError("成交记录条数必须为正整数")
            rows = self.db.execute("SELECT payload FROM paper_fills ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
            return [json.loads(row[0]) for row in reversed(rows)]

    def paper_nav_history(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM paper_nav ORDER BY day")]

    def _manifest(self):
        row = self.db.execute("SELECT payload FROM strategies WHERE id=?", (self.active,)).fetchone()
        if not row:
            raise ValueError("请先导入并选择策略")
        return validate_manifest(json.loads(row[0]))

    def _plan(self, *, allow_partial_quotes=False):
        if self.paper_only:
            raise ValueError("独立纸面策略仅通过下一合法开盘的cohort执行")
        manifest = self._manifest()
        if type(allow_partial_quotes) is not bool:
            raise ValueError("部分报价执行选项必须为布尔值")
        if allow_partial_quotes:
            try:
                origin = json.loads(manifest.get("source", ""))
            except (ValueError, TypeError):
                origin = None
            if (self.mode != "moomoo_simulate" or not isinstance(origin, dict)
                    or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"):
                raise ValueError("部分报价执行仅允许已授权的模拟盘执行计划")
        retry_generations = origin.get("retry_generations", {}) if allow_partial_quotes else {}
        if (not isinstance(retry_generations, dict) or any(
                not isinstance(code, str) or type(generation) is not int
                or not 0 <= generation <= 5
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
            identity_parts = [self.mode, self.account_id, manifest["strategy_id"], manifest["asof"], code]
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
                max_spread = min(self.limits["max_spread_bps"], 50) if allow_partial_quotes else self.limits["max_spread_bps"]
                if ask < bid or (ask - bid) / ((ask + bid) / 2) * 10000 > max_spread:
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
            if not self.halt_event.is_set() and not self.cancel_step.is_set():
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
                if status in {"FILLED_ALL", "FILLED_PART", "CANCELLED_PART", "FILLED"} and type(dealt) in (int, float):
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

    def state(self):
        with self.lock:
            fills = {row[0]: json.loads(row[1]) for row in self.db.execute("SELECT id,payload FROM order_fills")}
            orders = [{**dict(row), **fills.get(row["id"], {})} for row in
                      self.db.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 100")]
            return dict(mode=self.mode, account_id=self.account_id, running=not self.stop_event.is_set(), halted=self.halt_event.is_set(),
                halt_reason=self.halt_reason, active_strategy=self.active,
                strategies=[json.loads(r[0]) for r in self.db.execute("SELECT payload FROM strategies ORDER BY id")],
                limits=self.limits, connection=self.connection, account=self.account,
                orders=orders,
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
