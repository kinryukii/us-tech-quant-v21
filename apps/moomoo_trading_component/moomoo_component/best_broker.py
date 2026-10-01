"""A dedicated HGB diagonal strategy budget in the selected US SIMULATE account.

The research close timestamp remains in the archived source plan. The execution
manifest is created inside its next-open window, after funds and quotes checks.
No source refresh, training, REAL orders or trading unlock is implemented here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING
import json
import hashlib
import math
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from .core import Engine
from .brokers import BrokerError, BrokerOrderNotSent, BrokerReadError
from .strategy import timestamp, now_iso

SID = "HGB_DIAG_5"
REPRICE_INTERVAL_SECONDS = 30
MAX_REPRICES_PER_ORDER = 10
TERMINAL_RETRY_COOLDOWN_SECONDS = 30
MAX_TERMINAL_RETRIES_PER_CODE = 5
MARKET_BUY_CASH_BUFFER = 1.03


class BestBroker:
    def __init__(self, runtime_root, source, budget=10000, *, engine=None, now=None,
                 execution_delay_minutes=None, execution_window_seconds=None, allow_partial_quotes=None):
        if execution_window_seconds is not None and (
                type(execution_window_seconds) is not int or not 1 <= execution_window_seconds <= 3600):
            raise ValueError("模拟执行窗口必须是1至3600的整数秒")
        if allow_partial_quotes is not None and type(allow_partial_quotes) is not bool:
            raise ValueError("模拟逐票执行必须是明确布尔值")
        self.engine = engine or Engine(Path(runtime_root))
        self.source = source
        self.budget = float(budget)
        if not math.isfinite(self.budget) or self.budget <= 0:
            raise ValueError("模拟策略预算无效")
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.worker = None
        self.status = "STOPPED"
        self.reason = "尚未启动 MOOMOO 模拟策略"
        self.last_error = self.engine._get("best_last_error", "")
        self.plan = None
        self.metadata = {}
        self.snapshot = {}
        self.prepared_at = 0.0
        self.last_snapshot_at = 0.0
        self.prewarm_state = self.engine._get("best_subscription_prewarm", {})
        self._prewarm_key = None
        saved_window = self.engine._get("execution_window_seconds", 60)
        window = saved_window if execution_window_seconds is None else execution_window_seconds
        saved_partial = self.engine._get("allow_partial_quotes", False)
        partial = saved_partial if allow_partial_quotes is None else allow_partial_quotes
        if type(window) is not int or not 1 <= window <= 3600 or type(partial) is not bool:
            raise ValueError("持久模拟执行窗口或逐票配置无效")
        self.execution_window_seconds, self.allow_partial_quotes = window, partial
        saved_delay = self.engine._get("execution_delay_minutes", 0)
        delay = saved_delay if execution_delay_minutes is None else execution_delay_minutes
        if type(delay) is not int or not 0 <= delay <= 180:
            raise ValueError("模拟执行延迟必须为0至180整数分钟")
        self.execution_delay_minutes = delay
        if delay != saved_delay:
            self.engine._audit("EXECUTION_SCHEDULE_CHANGED", json.dumps({
                "previous_delay_minutes": saved_delay, "execution_delay_minutes": delay,
                "window_seconds": window, "effective_for_unexecuted_signals": True}))
        self.engine._set("execution_delay_minutes", delay)
        if window != saved_window or partial != saved_partial:
            self.engine._audit("EXECUTION_POLICY_CHANGED", json.dumps({
                "previous_window_seconds": saved_window, "execution_window_seconds": window,
                "previous_allow_partial_quotes": saved_partial, "allow_partial_quotes": partial}))
        self.engine._set("execution_window_seconds", window)
        self.engine._set("allow_partial_quotes", partial)

    def _scheduled_open(self, value):
        return timestamp(value) + timedelta(minutes=self.execution_delay_minutes)

    def _catchup_end(self):
        """Return a single explicitly authorized same-session deadline, if any."""
        record = self.engine._get("best_same_day_catchup", None)
        if not isinstance(record, dict) or record.get("signal_date") != self.metadata.get("signal_date"):
            return None
        state = self.engine._get("best_execution", {})
        if state.get("phase") != "BUY" or state.get("deferred_sells"):
            return None
        if not self.plan or not self.metadata.get("next_close_utc"):
            raise ValueError("当日补单缺少冻结计划或收盘身份")
        source_hash = self.plan.get("source_hash") or hashlib.sha256(json.dumps(
            self.plan.get("source_refs", self.metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest()
        account = self.engine._get("best_account", None)
        capital = self.engine._get("best_capital", None)
        deadline = timestamp(record["deadline_utc"])
        close = timestamp(self.metadata["next_close_utc"])
        ny = ZoneInfo("America/New_York")
        if (record.get("execution_date") != self.metadata.get("execution_date")
                or record.get("account_id") != account or self.engine.account_id != account
                or not isinstance(capital, dict) or capital.get("account_id") != account
                or capital.get("budget") != self.budget or record.get("budget") != self.budget
                or record.get("source_hash") != source_hash
                or not self.allow_partial_quotes
                or not self._scheduled_open(self.metadata["next_open_utc"]) < deadline <= close
                or deadline.astimezone(ny).date().isoformat() != record["execution_date"]):
            raise ValueError("当日补单授权与原模拟账户、冻结信号或交易时段不一致")
        return deadline

    def authorize_catchup(self, *, execution_date, deadline_utc, account_id, now):
        """Persist this user's one-day SIMULATE buy instruction while execution is stopped."""
        with self.lock:
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("先暂停模拟调度再建立当日补单意图")
            self.engine._require_stopped()
            if self.engine.halt_event.is_set() or self.engine._pending():
                raise ValueError("券商订单尚未完全核对或账户已锁定，禁止补单")
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("当日补单必须给出明确时区的当前时间")
            now = now.astimezone(timezone.utc)
            deadline = timestamp(deadline_utc)
            saved = self.engine._get("best_plan", None)
            state = self.engine._get("best_execution", {})
            account = self.engine._get("best_account", None)
            capital = self.engine._get("best_capital", None)
            if (not isinstance(saved, dict) or not isinstance(saved.get("metadata"), dict)
                    or not isinstance(saved.get("plan"), dict) or not isinstance(account, str)
                    or account_id != account or not isinstance(capital, dict)
                    or capital.get("account_id") != account or capital.get("budget") != self.budget):
                raise ValueError("冻结计划、原模拟账户或独立预算无法核实")
            metadata, plan = saved["metadata"], saved["plan"]
            original = state.get("manifest") or {}
            if not original:
                row = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (SID,)).fetchone()
                original = json.loads(row[0]) if row else {}
            ny = ZoneInfo("America/New_York")
            opening = timestamp(metadata["next_open_utc"])
            close = timestamp(metadata["next_close_utc"])
            scheduled = self._scheduled_open(metadata["next_open_utc"])
            if (metadata.get("execution_date") != execution_date
                    or metadata.get("signal_date") != state.get("signal_date")
                    or state.get("phase") != "BUY" or original.get("strategy_id") != SID
                    or state.get("deferred_sells") or not state.get("target_quantities")
                    or not self.allow_partial_quotes
                    or opening.astimezone(ny).date().isoformat() != execution_date
                    or now.astimezone(ny).date().isoformat() != execution_date
                    or not scheduled < now < deadline <= close
                    or deadline.astimezone(ny).date().isoformat() != execution_date):
                raise ValueError("仅允许原信号在同一纽约交易日正常时段补买")
            source_hash = plan.get("source_hash") or hashlib.sha256(json.dumps(
                plan.get("source_refs", metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest()
            try:
                origin = json.loads(original["source"])
            except (KeyError, TypeError, ValueError):
                raise ValueError("原模拟委托来源无法核实") from None
            if (origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                    or origin.get("signal_date") != metadata["signal_date"]
                    or origin.get("source_hash") != source_hash
                    or timestamp(origin["next_open_utc"]) != opening):
                raise ValueError("原模拟委托与冻结信号不一致")
            prior = self.engine._get("best_same_day_catchup", None)
            if isinstance(prior, dict) and prior.get("signal_date") == metadata["signal_date"]:
                if (prior.get("deadline_utc") == deadline.isoformat()
                        and prior.get("account_id") == account and prior.get("source_hash") == source_hash):
                    return prior
                raise ValueError("本信号已有不同的当日补单授权，禁止覆盖")
            if timestamp(original["expires_at"]) > now:
                raise ValueError("原委托窗口尚未结束，无需补单")
            rows = [dict(row) for row in self.engine.db.execute(
                "SELECT * FROM orders WHERE strategy_id=? AND mode='moomoo_simulate' AND account_id=?",
                (SID, account)) if timestamp(row["created_at"]) >= opening]
            if not rows or any(row["status"] not in {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED"}
                               for row in rows):
                raise ValueError("今天的原券商委托尚未全部终结并核对")
            record = dict(signal_date=metadata["signal_date"], execution_date=execution_date,
                account_id=account, budget=self.budget, source_hash=source_hash,
                authorized_at_utc=now.isoformat(), deadline_utc=deadline.isoformat(),
                original_deadline_utc=timestamp(original["expires_at"]).isoformat(),
                original_order_count=len(rows), reason="USER_REQUESTED_SAME_DAY_SIMULATE_BUY_CATCHUP")
            self.engine._set("best_same_day_catchup", record)
            self.engine._audit("BEST_SAME_DAY_CATCHUP_AUTHORIZED", json.dumps({
                **record, "account_id": "****" + account[-4:]}, ensure_ascii=False))
            return record

    def _execution_end(self):
        """Keep an already-sent signal's original deadline after policy changes."""
        catchup = self._catchup_end()
        if catchup is not None:
            return catchup
        opening = self._scheduled_open(self.metadata["next_open_utc"])
        configured = opening + timedelta(seconds=self.execution_window_seconds)
        state = self.engine._get("best_execution", {})
        manifest = state.get("manifest") or {}
        has_signal_order = any(timestamp(order["created_at"]) >= timestamp(self.metadata["next_open_utc"])
                               for order in self.engine.state()["orders"])
        if state.get("signal_date") == self.metadata.get("signal_date") and has_signal_order and not manifest:
            # A cycle with only stale quotes stores manifest=None. The last
            # imported strategy still carries the original submitted deadline.
            row = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (SID,)).fetchone()
            if row:
                candidate = json.loads(row[0])
                try:
                    origin = json.loads(candidate.get("source", ""))
                except (TypeError, ValueError):
                    origin = {}
                if (candidate.get("strategy_id") == SID
                        and origin.get("signal_date") == self.metadata["signal_date"]
                        and origin.get("next_open_utc") == self.metadata["next_open_utc"]):
                    manifest = candidate
        if (state.get("signal_date") == self.metadata.get("signal_date")
                and manifest.get("expires_at") and has_signal_order):
            original = timestamp(manifest["expires_at"])
            if original < configured:
                return original
        return configured

    def _prewarm(self, now, opening):
        close = self.metadata.get("next_close_utc")
        # Subscription-only warming does not read prices or make pre-market orders.
        if not close or not opening - timedelta(minutes=5) <= now < min(opening, timestamp(close)):
            return
        codes = {row["code"] for row in self.plan.get("rows", []) if row["target_weight"]}
        codes.update(code for code, position in self.snapshot.get("positions", {}).items() if position["qty"])
        if not codes:
            return
        key = hashlib.sha256(json.dumps({"signal_date": self.metadata["signal_date"],
            "execution_time_utc": opening.isoformat(), "codes": sorted(codes)}, sort_keys=True).encode()).hexdigest()
        previous = self.prewarm_state
        if self._prewarm_key == key or (previous.get("key") == key and previous.get("status") == "ERROR"
                and now < timestamp(previous["retry_after_utc"])):
            return
        self._require_running()
        note = dict(key=key, codes=sorted(codes), signal_date=self.metadata["signal_date"],
                    attempted_at_utc=now.isoformat(), basis="SUBSCRIPTION_ONLY_NOT_EXECUTABLE_QUOTES")
        try:
            self.engine.broker.prewarm(sorted(codes))
            self._prewarm_key = key
            note.update(status="SUBSCRIBED", reason="仅完成证券验证及订阅；正式执行仍需完整行情验证")
        except Exception as exc:
            note.update(status="ERROR", reason=str(exc), retry_after_utc=(now + timedelta(seconds=30)).isoformat())
        self.prewarm_state = note
        self.engine._set("best_subscription_prewarm", note)
        self.engine._audit("SUBSCRIPTION_PREWARM", json.dumps(note, ensure_ascii=False))

    def _connect(self):
        # Selection is constrained to the single account explicitly authorized
        # by the user. A changed or ambiguous identity never auto-selects.
        if self.engine.mode == "moomoo_simulate" and self.engine.broker is not None:
            capital = self.engine._get("best_capital", {})
            if capital.get("budget") != self.budget or capital.get("account_id") != self.engine.account_id:
                raise ValueError("已有模拟账户或预算与当前配置不一致")
            if self.engine.halt_event.is_set():
                raise ValueError(self.engine.halt_reason or "模拟账户已锁定")
            self.engine.broker.cancel_check = self._cancelled
            if self._recover_pending():
                return
            self._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
            return
        info = self.engine.connect(port=18441, security_firm="FUTUSECURITIES")
        if len(info["accounts"]) != 1:
            raise ValueError("需要核对唯一可用的美股模拟账户")
        account_id = info["accounts"][0]["account_id"]
        saved = self.engine._get("best_account", None)
        if saved is not None and saved != account_id:
            raise ValueError("模拟账户身份已变化，已停止自动选择")
        self.engine.set_mode("moomoo_simulate", account_id, "SIMULATE")
        self.engine.broker.cancel_check = self._cancelled
        capital = self.engine._get("best_capital", None)
        if capital and (capital["budget"] != self.budget or capital.get("account_id") != account_id):
            raise ValueError("已有模拟策略预算与启动参数不一致")
        if self.engine._pending():
            if not capital:
                raise ValueError("未完成委托缺少原模拟预算绑定，须先复核")
            if self._recover_pending():
                return
        snap = self.engine.broker.snapshot([], include_quotes=False)
        if capital is None:
            if snap["positions"] or snap["open_orders"]:
                raise ValueError("首次接入要求模拟账户空仓且无未完成委托")
            if snap["cash"] < self.budget:
                raise ValueError("模拟账户美元现金不足策略预算")
            capital = {"budget": self.budget, "account_id": account_id, "unused_cash": snap["cash"] - self.budget,
                       "initial_account_equity": snap["equity"], "started_at": now_iso()}
            self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_capital", json.dumps(capital)))
            self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_account", json.dumps(account_id)))
            self.engine.db.commit()
        if capital["budget"] != self.budget or capital.get("account_id", account_id) != account_id:
            raise ValueError("已有模拟策略预算与启动参数不一致")
        self._accept_snapshot(snap)
        # No additional stop-loss model is imposed on the frozen strategy.
        self.engine.set_limits(dict(max_order_notional=self.budget * 2,
            max_daily_turnover=self.budget * 4, max_position_notional=self.budget * 2,
            max_total_exposure=self.budget * 2, min_cash_reserve=capital["unused_cash"],
            max_daily_loss=capital["initial_account_equity"] * 2,
            max_orders_per_day=100, max_quote_age_seconds=30, max_spread_bps=50))
        if self.engine.halt_event.is_set():
            raise ValueError(self.engine.halt_reason or "账户已锁定，需核对订单")

    def _recover_pending(self):
        if not self.engine._pending():
            return False
        try:
            results = self.engine.reconcile()
            self._resolve_reprice_receipts(results)
        except BrokerReadError:
            self.status = "PENDING_RECONCILE"
            self.reason = "券商订单查询暂不可用；保留原委托并等待重新核对"
            return True
        if any(row.get("status") == "UNKNOWN" for row in results):
            self.engine.halt()
            raise ValueError("模拟委托结果未知，停止新委托并等待核对")
        if self.engine._pending():
            self.status = "PENDING_RECONCILE"
            self.reason = "保留原模拟委托，等待券商真实成交状态"
            return True
        return False

    def _accept_snapshot(self, snap):
        capital = self.engine._get("best_capital", None)
        if capital is None:
            raise ValueError("模拟预算尚未建立")
        if capital.get("account_id") != self.engine.account_id:
            raise ValueError("模拟策略预算绑定的账户身份不一致")
        expected = {}
        rows = self.engine.db.execute("SELECT o.code,o.side,f.payload FROM orders o LEFT JOIN order_fills f ON o.id=f.id WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=?", (SID, self.engine.account_id))
        for code, side, payload in rows:
            fill = json.loads(payload) if payload else {}
            qty = fill.get("fill_qty", 0)
            if qty and fill.get("fill_price") is None:
                self.engine._halt("券商已有成交但实际均价未能确认，请先复核")
                raise ValueError("券商实际成交均价未知，已停止新委托")
            expected[code] = expected.get(code, 0) + qty * (1 if side == "BUY" else -1)
        actual = {c: p["qty"] for c, p in snap["positions"].items() if p["qty"]}
        if actual != {c: q for c, q in expected.items() if q}:
            raise ValueError("模拟账户持仓与本策略已核对成交数量不一致，需先复核")
        self.snapshot = snap
        self.last_snapshot_at = time.monotonic()

    def start(self):
        with self.lock:
            if self.worker and self.worker.is_alive():
                return self.state()
            self._connect()
            self.engine.cancel_step.clear()
            self.stop_event.clear()
            self.status = "WAITING_OPEN"
            self.reason = "等待完整信号的计划执行时点"
            self.worker = threading.Thread(target=self._run, name="hgb-moomoo-simulation", daemon=True)
            self.worker.start()
            return self.state()

    def stop(self):
        self.stop_event.set()
        self.engine.stop()
        with self.lock:
            self.status = "STOPPED"
            self.reason = "暂停新委托；已发送模拟委托继续核对"

    def halt(self):
        self.stop_event.set()
        self.engine.halt()
        with self.lock:
            self.status = "HALTED"
            self.reason = self.engine.halt_reason

    def reconcile(self):
        """Synchronize broker receipts and account metadata while execution stays paused."""
        with self.lock:
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("请先暂停模拟自动执行并等待当前轮结束，再同步成交")
            self.engine._require_stopped()
            previous_error = self.last_error or self.engine._get("best_last_error", "")
            try:
                account = self.engine._get("best_account", None)
                capital = self.engine._get("best_capital", None)
                if (not isinstance(account, str) or not account or not isinstance(capital, dict)
                        or capital.get("account_id") != account or capital.get("budget") != self.budget):
                    raise ValueError("原模拟账户或策略预算绑定缺失或不一致，禁止同步")
                if self.engine.mode == "paper" and self.engine.broker is None:
                    info = self.engine.connect(port=18441, security_firm="FUTUSECURITIES")
                    accounts = info.get("accounts", [])
                    if (len(accounts) != 1 or str(accounts[0].get("account_id")) != account
                            or accounts[0].get("market") != "US" or accounts[0].get("environment") != "SIMULATE"):
                        raise ValueError("原唯一模拟账户身份无法确认，禁止同步")
                    self.engine.set_mode("moomoo_simulate", account, "SIMULATE")
                elif (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                        or self.engine.account_id != account
                        or str(self.engine.broker.account_id) != account):
                    raise ValueError("当前模拟账户与原策略绑定不一致，禁止同步")
                self.engine.broker.cancel_check = self._cancelled
                saved = self.engine._get("best_plan", None)
                if saved:
                    if not isinstance(saved.get("metadata"), dict) or not isinstance(saved.get("plan"), dict):
                        raise ValueError("原冻结模拟计划无法读取，禁止改写计划")
                    self.metadata, self.plan = saved["metadata"], saved["plan"]
                results = self.engine.reconcile()
                self._resolve_reprice_receipts(results)
                if any(row.get("status") == "UNKNOWN" for row in results):
                    raise ValueError("原模拟委托仍无法确认，保留暂停并等待核对")
                snapshot = self.engine.broker.snapshot([], include_quotes=False)
                if snapshot.get("funds_only") is not True or snapshot.get("quotes") != {}:
                    raise ValueError("只读资金持仓快照不完整，禁止作为成交同步证据")
                self._accept_snapshot(snapshot)
                if snapshot["cash"] < capital["unused_cash"]:
                    raise ValueError("模拟账户现金低于独立策略保留资金，保持暂停并复核")
                self.engine._audit("BEST_RECONCILE_SYNCED", json.dumps({
                    "previous_last_error": previous_error, "receipt_count": len(results),
                    "pending_order_count": len(self.engine._pending()),
                    "automatic_execution_paused": True, "halt_preserved": self.engine.halt_event.is_set(),
                    "valuation_basis": "BROKER_ACCOUNT_METADATA"}, ensure_ascii=False))
                self.last_error = ""
                self.engine._set("best_last_error", "")
                self.status = "HALTED" if self.engine.halt_event.is_set() else "STOPPED"
                self.reason = "已同步券商真实成交与持仓；自动执行仍暂停"
                if self.engine._pending():
                    self.reason += "，未完成委托继续等待回报"
                return self.state()
            except Exception as exc:
                self.status = "BLOCKED"
                self.last_error = str(exc)
                self.reason = "成交同步未完成；自动执行仍暂停：" + self.last_error
                self.engine._set("best_last_error", self.last_error)
                self.engine._audit("BEST_RECONCILE_BLOCKED", json.dumps({
                    "previous_last_error": previous_error, "reason": self.last_error,
                    "automatic_execution_paused": True}, ensure_ascii=False))
                raise

    def _run(self):
        while not self.stop_event.is_set():
            wait_seconds = 1
            try:
                self.tick()
            except Exception as exc:
                with self.lock:
                    self.status = (("PENDING_RECONCILE" if self.engine._pending() else "WAITING_QUOTES")
                                   if isinstance(exc, BrokerReadError) else "BLOCKED")
                    self.last_error = str(exc)
                    self.reason = self.last_error
                    self.engine._set("best_last_error", self.last_error)
                if isinstance(exc, BrokerReadError):
                    wait_seconds = exc.retry_after_seconds
                    self.engine._audit("BROKER_READ_COOLDOWN", json.dumps({
                        "reason": str(exc), "retry_after_seconds": wait_seconds,
                        "failed_operation": "READ_ONLY_QUERY",
                        "automatic_order_retry": False}, ensure_ascii=False))
                # A durable unknown order or a halt requires manual review.
                if self.engine.halt_event.is_set():
                    self.stop_event.set()
            self.stop_event.wait(wait_seconds)

    def _cancelled(self):
        return self.stop_event.is_set() or self.engine.halt_event.is_set() or self.engine.cancel_step.is_set()

    def _require_running(self):
        if self.stop_event.is_set() or self.engine.halt_event.is_set():
            raise ValueError("模拟策略已停止，禁止新委托")

    def _book(self):
        capital = self.engine._get("best_capital", {})
        return {"cash": self.snapshot.get("cash", 0) - capital.get("unused_cash", 0),
                "positions": {code: p["qty"] for code, p in self.snapshot.get("positions", {}).items()}}

    def _prepare(self, now):
        self.prepared_at = time.monotonic()
        self._require_running()
        metadata = self.source.status(now=now)
        self.metadata = metadata
        day = metadata.get("signal_date") or metadata.get("latest_completed_signal_date")
        if not day:
            self.status = "WAITING_CLOSE"
            self.reason = metadata.get("reason", "等待完整信号日")
            return
        if metadata.get("data_gaps"):
            self.status = metadata.get("status", "WAITING_SOURCE")
            self.reason = "等待日更生成最新完整信号；保留当前账户记录"
            self.plan = None
            return
        saved = self.engine._get("best_plan", None)
        if saved and saved.get("metadata", {}).get("signal_date") == day:
            self.plan = saved["plan"]
            self.metadata = {**saved["metadata"], **{k: metadata[k] for k in
                ("status", "reason", "ready", "execute_now", "next_expected_open_utc") if k in metadata}}
            self.status = self.metadata.get("status", "BLOCKED")
            self.reason = self.metadata.get("reason", "等待下一开盘")
            return
        self._require_running()
        states = self.source.close_states({SID: self._book()}, signal_date=day)
        self._require_running()
        result = self.source.load(states, now=now)
        self.metadata = {k: v for k, v in result.items() if k != "plans"}
        self.plan = result.get("plans", {}).get(SID)
        self.status = result.get("status", "BLOCKED")
        self.reason = result.get("reason", "等待下一开盘")
        if self.plan:
            self.engine._set("best_plan", {"metadata": self.metadata, "plan": self.plan, "close_state": states[SID]})

    def _execution(self, now, phase):
        self._require_running()
        if self.allow_partial_quotes:
            codes = {row["code"] for row in self.plan.get("rows", []) if row["target_weight"]}
            codes.update(self.snapshot.get("positions", {}))
            snap = self.engine.broker.snapshot_partial(sorted(codes))
            self._require_running()
            self._accept_snapshot(snap)
            return self._partial_execution(now, phase, snap)
        state = self.engine._get("best_execution", {})
        day = self.metadata["signal_date"]
        if state.get("signal_date") == day and state.get("phase") == phase:
            return state
        rows = self.plan.get("rows", [])
        weights = {row["code"]: float(row["target_weight"]) for row in rows}
        if any(w < 0 or w > .100001 for w in weights.values()) or sum(weights.values()) > 1.000001:
            raise ValueError("HGB 对角风险目标超出冻结仓位约束")
        codes = sorted(set(weights) | set(self.snapshot["positions"]))
        snap = self.engine.broker.snapshot(codes)
        self._require_running()
        self._accept_snapshot(snap)
        capital = self.engine._get("best_capital", {})
        equity = snap["cash"] - capital["unused_cash"] + sum(p["market_value"] for p in snap["positions"].values())
        if equity <= 0 or snap["cash"] < capital["unused_cash"]:
            raise ValueError("独立模拟策略预算已不足，禁止使用其余模拟现金")
        self.engine.set_limits(dict(max_order_notional=equity * 2,
            max_daily_turnover=equity * 4, max_position_notional=equity * 2,
            max_total_exposure=equity * 2, min_cash_reserve=capital["unused_cash"]))
        targets = []
        for code in codes:
            qty = snap["positions"].get(code, {}).get("qty", 0)
            q = snap["quotes"][code]
            ask, lot = q["ask"], q["lot_size"]
            target = math.floor(weights.get(code, 0) * equity / (ask * 1.005) / lot) * lot
            if phase == "SELL":
                target = min(target, qty)
            targets.append({"code": code, "target_qty": int(target)})
        if not targets:
            return {"signal_date": day, "phase": "DONE"}
        execution_at = self._scheduled_open(self.metadata["next_open_utc"])
        end = execution_at + timedelta(seconds=self.execution_window_seconds)
        manifest = dict(schema_version=1, strategy_id=SID, name="HGB＋对角风险 · MOOMOO 模拟",
            revision=f"{day}:{phase}", asof=now.isoformat(), expires_at=end.isoformat(), provenance="live",
            targets=targets, source=json.dumps({"kind": "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN",
                "signal_date": day, "signal_close_utc": self.metadata.get("signal_close_utc"),
                "next_open_utc": self.metadata["next_open_utc"],
                "execution_time_utc": execution_at.isoformat(),
                "execution_delay_minutes": self.execution_delay_minutes,
                "source_hash": self.plan.get("source_hash") or hashlib.sha256(json.dumps(self.plan.get("source_refs", self.metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest(),
                "budget": self.budget, "phase": phase, "research_broker_action_allowed": False}, ensure_ascii=False))
        self.engine.import_strategy(manifest)
        self.engine.switch(SID)
        state = {"signal_date": day, "phase": phase, "manifest": manifest}
        self.engine._set("best_execution", state)
        return state

    def _partial_execution(self, now, phase, snap, deferred_sells=None, sell_codes=None, resume_buy_state=None):
        """Build only quote-qualified targets; preserve original weights and each first resolved quantity."""
        day = self.metadata["signal_date"]
        previous = self.engine._get("best_execution", {})
        if previous.get("signal_date") != day or previous.get("phase") != phase:
            previous = {}
        if phase == "SELL":
            sell_codes = sell_codes if sell_codes is not None else previous.get("sell_codes")
            resume_buy_state = resume_buy_state if resume_buy_state is not None else previous.get("resume_buy_state")
        quantities = dict(previous.get("target_quantities", {}))
        processed = set(previous.get("processed_codes", []))
        weights = {row["code"]: float(row["target_weight"]) for row in self.plan.get("rows", [])}
        if any(not math.isfinite(weight) or not 0 <= weight <= .100001 for weight in weights.values()) or sum(weights.values()) > 1.000001:
            raise ValueError("HGB 对角风险目标超出冻结仓位约束")
        capital = self.engine._get("best_capital", {})
        cash = snap["cash"] - capital["unused_cash"]
        equity = cash + sum(position["market_value"] for position in snap["positions"].values())
        if cash < 0 or equity <= 0:
            raise ValueError("独立模拟策略预算已不足，禁止使用其余模拟现金")
        self.engine.set_limits(dict(max_order_notional=equity * 2, max_daily_turnover=equity * 4,
            max_position_notional=equity * 2, max_total_exposure=equity * 2,
            min_cash_reserve=capital["unused_cash"]))
        orders = [row for row in self.engine.state()["orders"]
                  if timestamp(row["created_at"]) >= timestamp(self.metadata["next_open_utc"])]
        attempts_by_code = {}
        for order in orders:
            if order["status"] != "CANCELLED_BEFORE_SEND":
                attempts_by_code.setdefault((order["code"], order["side"]), []).append(order)
        attempted = {code: rows[-1] for (code, side), rows in attempts_by_code.items() if side == phase}
        cooldowns = self.engine._get("best_terminal_retry_cooldowns", {})
        cooldowns_changed = False
        retry_generations = {}
        deferred = list(deferred_sells if deferred_sells is not None else previous.get("deferred_sells", []))
        skipped = list(deferred) + [row for row in previous.get("skipped", [])
                                    if row.get("cash_limited")]
        targets = []
        codes = set(snap["positions"]) if phase == "SELL" else {code for code, weight in weights.items() if weight}
        if phase == "SELL" and sell_codes is not None:
            codes.intersection_update(sell_codes)
        for code in sorted(codes, key=lambda code: (-weights.get(code, 0), code)):
            qty = snap["positions"].get(code, {}).get("qty", 0)
            attempts = attempts_by_code.get((code, phase), [])
            prior = attempts[-1] if attempts else None
            if prior:
                terminal_buy = (phase == "BUY" and prior["status"] in
                                {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                                and qty < quantities.get(code, qty))
                if terminal_buy:
                    if len(attempts) > MAX_TERMINAL_RETRIES_PER_CODE:
                        processed.add(code)
                    else:
                        observed_at = cooldowns.get(prior["id"])
                        if not observed_at:
                            observed_at = now.isoformat()
                            cooldowns[prior["id"]] = observed_at
                            cooldowns_changed = True
                        if (now - timestamp(observed_at)).total_seconds() < TERMINAL_RETRY_COOLDOWN_SECONDS:
                            processed.discard(code)
                            skipped.append(dict(code=code, reason="原买单已确认失败；冷却后按最新合格报价重试",
                                                retry_after_utc=(timestamp(observed_at) + timedelta(seconds=TERMINAL_RETRY_COOLDOWN_SECONDS)).isoformat()))
                            continue
                        processed.discard(code)
                        retry_generations[code] = len(attempts)
                else:
                    processed.add(code)
            if code in processed:
                prior = attempted.get(code)
                if prior and prior["status"] in {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}:
                    skipped.append(dict(code=code, reason="本信号委托已终结，保留实际成交，不重复发送", already_attempted=True))
                continue
            quote = snap["quotes"].get(code)
            reason = snap.get("quote_errors", {}).get(code)
            if not quote:
                skipped.append(dict(code=code, reason=reason or "尚未取得合格真实报价"))
                continue
            spread = (quote["ask"] - quote["bid"]) / ((quote["ask"] + quote["bid"]) / 2) * 10000
            price = quote["bid"] if phase == "SELL" else quote["ask"]
            if spread > self.engine.limits["max_spread_bps"] or abs(price / quote["price"] - 1) > .02:
                skipped.append(dict(code=code, reason="真实盘口价差或价格偏离超过原执行限制"))
                continue
            if code not in quantities:
                # MARKET has no execution-price ceiling. Keep extra strategy
                # cash uncommitted when sizing new BUY intents.
                buy_reserve = 1.005 * MARKET_BUY_CASH_BUFFER
                desired = math.floor(weights.get(code, 0) * equity / (quote["ask"] * (buy_reserve if phase == "BUY" else 1.005)) / quote["lot_size"]) * quote["lot_size"]
                if phase == "SELL":
                    quantities[code] = min(desired, qty)
                else:
                    affordable = math.floor(max(0, cash) / (quote["ask"] * buy_reserve) / quote["lot_size"]) * quote["lot_size"]
                    quantities[code] = max(qty, min(desired, qty + affordable))
                    if desired > quantities[code]:
                        skipped.append(dict(code=code, reason="可用策略现金不足，保留原目标权重及未买入差额", cash_limited=True))
            target = quantities[code]
            if phase == "BUY" and (code in retry_generations or self._catchup_end() is not None):
                affordable = math.floor(max(0, cash) / (quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER) / quote["lot_size"]) * quote["lot_size"]
                cap = math.floor(weights[code] * equity / (quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER) / quote["lot_size"]) * quote["lot_size"]
                target = max(qty, min(target, qty + affordable, cap))
            if phase == "BUY":
                cash -= max(0, target - qty) * quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER
            if target == qty:
                processed.add(code)
                continue
            targets.append(dict(code=code, target_qty=target))
        if cooldowns_changed:
            self.engine._set("best_terminal_retry_cooldowns", cooldowns)
        prior_manifest = previous.get("manifest") or {}
        manifest = None
        if targets:
            end = self._execution_end()
            source_hash = self.plan.get("source_hash") or hashlib.sha256(json.dumps(
                self.plan.get("source_refs", self.metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest()
            manifest = dict(schema_version=1, strategy_id=SID, name="HGB＋对角风险 · MOOMOO 模拟",
                revision=f"{day}:{phase}", asof=prior_manifest.get("asof", previous.get("phase_asof", now.isoformat())),
                expires_at=end.isoformat(), provenance="live", targets=targets,
                source=json.dumps(dict(kind="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN", signal_date=day,
                    signal_close_utc=self.metadata["signal_close_utc"], next_open_utc=self.metadata["next_open_utc"],
                    execution_time_utc=self._scheduled_open(self.metadata["next_open_utc"]).isoformat(),
                    execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds,
                    source_hash=source_hash, budget=self.budget, phase=phase,
                    retry_generations={code: retry_generations.get(code, 0) for code in (target["code"] for target in targets)},
                    allow_partial_quotes=True, research_broker_action_allowed=False), ensure_ascii=False))
            self.engine.import_strategy(manifest)
            self.engine.switch(SID)
        state = dict(signal_date=day, phase=phase, manifest=manifest,
            phase_asof=previous.get("phase_asof", prior_manifest.get("asof", now.isoformat())),
            target_quantities=quantities, processed_codes=sorted(processed), skipped=skipped,
            retry_generations=retry_generations,
            deferred_sells=deferred, original_target_weights=weights,
            valuation_basis="BROKER_ACCOUNT_METADATA", original_target_cash_weight=self.plan["target_cash_weight"])
        if phase == "SELL" and resume_buy_state is not None:
            state.update(sell_codes=sorted(sell_codes), resume_buy_state=resume_buy_state)
        self.engine._set("best_execution", state)
        return state

    def _tick_partial(self, now):
        previous = self.engine._get("best_execution", {})
        day = self.metadata["signal_date"]
        if previous.get("signal_date") == day and previous.get("phase") == "DONE":
            self.status = previous.get("completion_status", "EXECUTED")
            self.reason = "本信号已处理；保留实际成交与未成交明细，不重复发送"
            return
        codes = {row["code"] for row in self.plan.get("rows", []) if row["target_weight"]}
        codes.update(self.snapshot.get("positions", {}))
        snap = self.engine.broker.snapshot_partial(sorted(codes))
        self._require_running()
        self._accept_snapshot(snap)
        phase = previous.get("phase", "SELL") if previous.get("signal_date") == day else "SELL"
        if phase == "BUY" and previous.get("deferred_sells"):
            sell_codes = {row["code"] for row in previous["deferred_sells"]}
            state = self._partial_execution(now, "SELL", snap, sell_codes=sell_codes, resume_buy_state=previous)
            phase = "SELL"
        else:
            state = self._partial_execution(now, phase, snap)
        if phase == "SELL" and not state["manifest"]:
            deferred = [row for row in state["skipped"] if row["code"] in snap["positions"]]
            if state.get("resume_buy_state") is not None:
                self.engine._set("best_execution", state["resume_buy_state"])
            state = self._partial_execution(now, "BUY", snap, deferred_sells=deferred)
        if not state["manifest"]:
            unresolved = [row for row in state["skipped"] if not row.get("already_attempted")]
            if not unresolved:
                state.update(phase="DONE", completion_status="PARTIALLY_EXECUTED" if state["skipped"] else "EXECUTED")
                self.engine._set("best_execution", state)
                self.status = state["completion_status"]
                self.reason = "本信号目标已处理；成交以券商真实对账为准"
            else:
                actual = any(row.get("fill_qty", 0) > 0 for row in self.engine.state()["orders"]
                             if timestamp(row["created_at"]) >= timestamp(self.metadata["next_open_utc"]))
                self.status = ("RETRY_COOLDOWN" if any(row.get("retry_after_utc") for row in unresolved)
                               else "PARTIALLY_EXECUTED" if actual else "WAITING_QUOTES")
                self.reason = "; ".join(row["code"] + ": " + row["reason"] for row in unresolved)
            return
        result = self.engine.step(respect_cancel=True, allow_partial_quotes=True,
                                  broker_order_type="MARKET")
        skipped = result.get("skipped", [])
        if skipped:
            state["skipped"].extend(skipped)
            self.engine._set("best_execution", state)
        if any(row.get("retry_after_seconds") == 30 for row in skipped):
            raise BrokerReadError("只读账户查询暂未成功；30 秒后重新查询，尚未送出订单")
        self.status = "PENDING_RECONCILE" if result.get("submitted") else "WAITING_QUOTES"
        self.reason = "合格股票逐笔提交后先对账；未送出的股票保留原因并在本窗口重试"

    def _replace_unsubmitted_schedule(self, now):
        """Archive an obsolete intent only when this signal never sent an order."""
        state = self.engine._get("best_execution", {})
        if state.get("signal_date") != self.metadata.get("signal_date") or state.get("phase") == "DONE":
            return
        manifest = state.get("manifest")
        if not manifest:
            return
        ending = self._execution_end()
        if timestamp(manifest["expires_at"]) == ending:
            return
        origin = json.loads(manifest["source"])
        source_hash = self.plan.get("source_hash") or hashlib.sha256(json.dumps(
            self.plan.get("source_refs", self.metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest()
        actual_open = timestamp(self.metadata["next_open_utc"])
        if (state.get("phase") not in {"SELL", "BUY"} or manifest.get("strategy_id") != SID
                or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or origin.get("signal_date") != self.metadata["signal_date"]
                or timestamp(origin["next_open_utc"]) != actual_open or origin.get("source_hash") != source_hash):
            raise ValueError("旧模拟执行意图与冻结信号不一致，禁止改写")
        orders = self.engine.state()["orders"]
        if self.engine._pending() or any(timestamp(order["created_at"]) >= actual_open for order in orders):
            if now >= timestamp(manifest["expires_at"]) and timestamp(manifest["expires_at"]) < ending:
                # A submitted signal retains its original deadline; later signals use the new policy.
                return
            raise ValueError("本信号已有模拟委托记录，保留原执行意图并等待核对，禁止重建买卖")
        history = self.engine._get("best_execution_schedule_history", [])
        history.append({"archived_at": now.isoformat(), "execution": state,
                        "replacement_expires_at": ending.isoformat(), "reason": "AUTHORIZED_DELAY_CHANGE_NO_ORDERS"})
        self.engine._set("best_execution_schedule_history", history)
        self.engine._audit("UNSUBMITTED_EXECUTION_SCHEDULE_REPLACED", json.dumps({
            "signal_date": state["signal_date"], "previous_expires_at": manifest["expires_at"],
            "replacement_expires_at": ending.isoformat(), "orders_for_signal": 0}, ensure_ascii=False))
        self.engine._set("best_execution", {})

    def _resolve_reprice_receipts(self, receipts):
        """Recover a durable same-order amendment without submitting another order."""
        attempts = self.engine._get("best_order_reprices", {})
        changed = False
        for receipt in receipts:
            order_id = receipt.get("order_id")
            for client_id, attempt in attempts.items():
                if attempt.get("status") != "ATTEMPTING" or attempt.get("order_id") != order_id:
                    continue
                status = receipt.get("status")
                amendment_confirmed = (receipt.get("qty") == attempt.get("qty")
                                       and receipt.get("limit_price") == attempt.get("limit_price"))
                if status in {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED", "DISABLED", "DELETED"}:
                    attempt["status"] = "RESOLVED_TERMINAL"
                elif amendment_confirmed:
                    attempt["status"] = "ACKNOWLEDGED"
                else:
                    continue
                if amendment_confirmed:
                    self.engine.db.execute("UPDATE orders SET qty=?,limit_price=? WHERE id=?",
                                           (attempt["qty"], attempt["limit_price"], client_id))
                    self.engine.db.commit()
                changed = True
        if changed:
            self.engine._set("best_order_reprices", attempts)

    def _maybe_reprice_pending(self, now):
        """Requote one confirmed open BUY by amending its existing broker order ID."""
        if not self.allow_partial_quotes or not self.plan or not self.metadata.get("next_open_utc"):
            return
        execution_at = self._scheduled_open(self.metadata["next_open_utc"])
        if not execution_at <= now < self._execution_end():
            return
        pending = self.engine._pending()
        if len(pending) != 1:
            return
        row = pending[0]
        if row["side"] != "BUY" or row["status"] not in {"SUBMITTED", "FILLED_PART"} or not row["order_id"]:
            return
        if row.get("order_type", "NORMAL") == "MARKET":
            return
        state = self.engine._get("best_execution", {})
        if state.get("signal_date") != self.metadata.get("signal_date") or state.get("phase") != "BUY":
            return
        attempts = self.engine._get("best_order_reprices", {})
        prior = attempts.get(row["id"], {})
        if prior.get("status") in {"ATTEMPTING", "UNKNOWN"}:
            return
        if prior.get("count", 0) >= MAX_REPRICES_PER_ORDER:
            return
        last_at = timestamp(prior["attempted_at"]) if prior.get("attempted_at") else timestamp(row["created_at"])
        if (now - last_at).total_seconds() < REPRICE_INTERVAL_SECONDS:
            return
        weight = next((float(item["target_weight"]) for item in self.plan["rows"]
                       if item["code"] == row["code"]), 0)
        if not 0 < weight <= .100001:
            return
        snap = self.engine.broker.snapshot_partial([row["code"]])
        self._require_running()
        self._accept_snapshot(snap)
        quote = snap["quotes"].get(row["code"])
        if quote is None:
            return
        bid, ask, reference = (float(quote[k]) for k in ("bid", "ask", "price"))
        age = (now - timestamp(quote["asof"])).total_seconds()
        if (not quote["tradable"] or not 0 <= age <= 30 or bid <= 0 or ask < bid
                or (ask - bid) / ((ask + bid) / 2) * 10000 > 50
                or abs(ask / reference - 1) > .02):
            return
        tick = Decimal(str(quote["price_tick"]))
        lot = int(quote["lot_size"])
        if tick <= 0 or lot < 1 or float(lot) != float(quote["lot_size"]):
            return
        price = float((Decimal(str(ask)) / tick).to_integral_value(rounding=ROUND_CEILING) * tick)
        original_price = float(prior.get("original_limit_price", row["limit_price"]))
        if abs(price / original_price - 1) > .02 or price == row["limit_price"]:
            return
        capital = self.engine._get("best_capital", {})
        strategy_equity = (Decimal(str(snap["cash"])) - Decimal(str(capital.get("unused_cash", 0)))
                           + sum(Decimal(str(position["market_value"]))
                                 for position in snap["positions"].values()))
        if strategy_equity <= 0:
            return
        cap = Decimal(str(weight)) * strategy_equity / Decimal("1.005")
        view = next((item for item in self.engine.state()["orders"] if item["id"] == row["id"]), None)
        filled_qty = int(view.get("fill_qty") or 0) if view else 0
        held_qty = int(snap["positions"].get(row["code"], {}).get("qty", 0))
        max_position_qty = int(cap // (Decimal(str(price)) * lot)) * lot
        proposed_qty = min(row["qty"], filled_qty + max(0, max_position_qty - held_qty))
        if proposed_qty <= filled_qty or proposed_qty <= 0:
            return
        strategy_cash = Decimal(str(snap["cash"])) - Decimal(str(capital.get("unused_cash", 0)))
        old_outstanding = Decimal(row["qty"] - filled_qty) * Decimal(str(row["limit_price"]))
        new_outstanding = Decimal(proposed_qty - filled_qty) * Decimal(str(price))
        extra_cash = max(Decimal("0"), new_outstanding - old_outstanding) * Decimal("1.005")
        if strategy_cash < 0 or extra_cash > strategy_cash:
            return
        proposed = dict(code=row["code"], side="BUY", qty=proposed_qty,
                        limit_price=price, max_order_notional=float(cap))
        attempt = dict(order_id=row["order_id"], qty=proposed_qty, limit_price=price,
                       original_limit_price=original_price, attempted_at=now.isoformat(),
                       count=prior.get("count", 0) + 1, status="ATTEMPTING")
        attempts[row["id"]] = attempt
        self.engine._set("best_order_reprices", attempts)  # durable before SDK I/O
        deadline = self._execution_end().isoformat()
        try:
            result = self.engine.broker.reprice(proposed, row["order_id"], row["id"],
                expected_dealt_qty=filled_qty, execution_deadline_utc=deadline)
        except (BrokerReadError, BrokerOrderNotSent):
            attempt["status"] = "NOT_SENT"
            self.engine._set("best_order_reprices", attempts)
            raise
        except Exception:
            attempt["status"] = "UNKNOWN"
            self.engine._set("best_order_reprices", attempts)
            self.engine._halt("模拟改单结果未知；保留原订单号，停止自动委托并等待核对")
            raise
        if (result.get("order_id") != row["order_id"] or result.get("qty") != proposed_qty
                or result.get("limit_price") != price):
            attempt["status"] = "UNKNOWN"
            self.engine._set("best_order_reprices", attempts)
            self.engine._halt("模拟改单回执与原订单号或目标不符；停止自动委托并等待核对")
            raise BrokerError("模拟改单回执无法核对")
        attempt["status"] = "ACKNOWLEDGED"
        self.engine.db.execute("UPDATE orders SET qty=?,limit_price=? WHERE id=?",
                               (proposed_qty, price, row["id"]))
        self.engine.db.commit()
        self.engine._set("best_order_reprices", attempts)
        self.engine._audit("BEST_ORDER_REPRICED", json.dumps(dict(
            code=row["code"], order_id=row["order_id"], previous_qty=row["qty"],
            qty=proposed_qty, previous_limit_price=row["limit_price"], limit_price=price,
            count=attempt["count"]), ensure_ascii=False))

    def tick(self, now=None):
        with self.lock:
            if self.stop_event.is_set():
                return
            now = now or self._now()
            if now.tzinfo is None:
                raise ValueError("执行时间必须明确时区")
            if self.engine._pending():
                results = self.engine.reconcile()
                self._resolve_reprice_receipts(results)
                if any(r.get("status") == "UNKNOWN" for r in results):
                    self.engine.halt()
                    raise ValueError("模拟委托结果未知，停止新委托并等待核对")
                if self.engine._pending():
                    self._maybe_reprice_pending(now)
                    self.status = "PENDING_RECONCILE"
                    self.reason = "已发送模拟委托，等待券商成交状态"
                    return
                self._require_running()
                snap = self.engine.broker.snapshot([], include_quotes=False)
                self._accept_snapshot(snap)
            if time.monotonic() - self.prepared_at > 60:
                self._require_running()
                if time.monotonic() - self.last_snapshot_at > 60:
                    self._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
                self._prepare(now)
            open_value = self.metadata.get("next_open_utc")
            if not open_value or not self.plan:
                return
            market_open = timestamp(open_value)
            opening = self._scheduled_open(open_value)
            close = timestamp(self.metadata["signal_close_utc"])
            ny = ZoneInfo("America/New_York")
            if (self.metadata["signal_date"] >= self.metadata["execution_date"] or close >= market_open
                    or close > now or close.astimezone(ny).date().isoformat() != self.metadata["signal_date"]
                    or market_open.astimezone(ny).date().isoformat() != self.metadata["execution_date"]):
                raise ValueError("收盘信号与下一交易日开盘身份不一致")
            self._replace_unsubmitted_schedule(now)
            if now < opening:
                self._prewarm(now, opening)
                self._require_running()
                self.status = "WAITING_OPEN"
                self.reason = "已准备目标，等待美东 " + opening.astimezone(ny).strftime("%H:%M") + " 的计划执行时点"
                return
            if now >= self._execution_end():
                finished = self.engine._get("best_execution", {})
                if finished.get("signal_date") == self.metadata["signal_date"] and finished.get("phase") == "DONE":
                    self.status = finished.get("completion_status", "EXECUTED")
                    self.reason = "本信号已处理；保留实际成交及未成交明细，不补发"
                    return
                partial = self.allow_partial_quotes and any(row.get("fill_qty", 0) > 0 for row in self.engine.state()["orders"]
                    if timestamp(row["created_at"]) >= market_open)
                self.status = "PARTIALLY_EXECUTED" if partial else "MISSED_OPEN"
                self.reason = "本期计划执行窗口已结束，等待下一个完整信号；未补发旧买卖"
                return
            if self.metadata.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}:
                return
            if self.allow_partial_quotes:
                return self._tick_partial(now)
            self._require_running()
            state = self.engine._get("best_execution", {})
            if state.get("signal_date") != self.metadata["signal_date"]:
                state = self._execution(now, "SELL")
            if state.get("phase") == "DONE":
                self.status = "EXECUTED"
                self.reason = "本期开盘目标已完成，等待下一完整信号"
                return
            manifest = state["manifest"]
            self._require_running()
            self.engine.import_strategy(manifest)
            self.engine.switch(SID)
            # Target attainment is determined from the selected broker account,
            # never the local paper book or a submitted order's limit price.
            snap = self.engine.broker.snapshot([t["code"] for t in manifest["targets"]])
            self._require_running()
            self._accept_snapshot(snap)
            reached = all(snap["positions"].get(t["code"], {}).get("qty", 0) == t["target_qty"] for t in manifest["targets"])
            if reached:
                if state["phase"] == "SELL":
                    self._execution(now, "BUY")
                    return
                state["phase"] = "DONE"
                self.engine._set("best_execution", state)
                self.status = "EXECUTED"
                self.reason = "本期开盘目标已由券商模拟成交确认"
                return
            attempted = {o["code"]: o for o in self.engine.state()["orders"]
                         if o["created_at"] >= manifest["asof"]}
            for target in manifest["targets"]:
                qty = snap["positions"].get(target["code"], {}).get("qty", 0)
                prior = attempted.get(target["code"])
                if qty != target["target_qty"] and prior:
                    self.status = "BLOCKED"
                    self.reason = "本期开盘委托已终结但未达目标；保留实际成交，不补发同一信号"
                    return
            self._require_running()
            self.engine.step(respect_cancel=True)
            self.status = "PENDING_RECONCILE"
            self.reason = "已按策略差额提交一笔模拟委托，先对账再继续"

    def state(self):
        with self.lock:
            e = self.engine.state()
            capital = self.engine._get("best_capital", None)
            cash = equity = None
            if capital and self.snapshot:
                cash = self.snapshot["cash"] - capital["unused_cash"]
                equity = cash + sum(p["market_value"] for p in self.snapshot.get("positions", {}).values())
            orders = []
            reprice_attempts = self.engine._get("best_order_reprices", {})
            terminal_cooldowns = self.engine._get("best_terminal_retry_cooldowns", {})
            for order in e["orders"]:
                item = dict(order)
                item["account_id"] = "****" + str(item["account_id"])[-4:]
                item["dealt_qty"] = item.get("fill_qty")
                item["dealt_avg_price"] = item.get("fill_price")
                amendment = reprice_attempts.get(item["id"], {})
                item["reprice_count"] = amendment.get("count", 0)
                item["last_reprice_at"] = amendment.get("attempted_at")
                item["last_reprice_limit"] = amendment.get("limit_price")
                item["reprice_status"] = amendment.get("status")
                terminal_at = terminal_cooldowns.get(item["id"])
                item["terminal_retry_after_utc"] = (
                    (timestamp(terminal_at) + timedelta(seconds=TERMINAL_RETRY_COOLDOWN_SECONDS)).isoformat()
                    if terminal_at else None)
                orders.append(item)
            account_id = e["account_id"]
            execution_at = self._scheduled_open(self.metadata["next_open_utc"]) if self.metadata.get("next_open_utc") else None
            expected_at = (self._scheduled_open(self.metadata["next_expected_open_utc"])
                           if self.metadata.get("next_expected_open_utc") else None)
            if execution_at and self._now() < self._execution_end() and self.status != "EXECUTED":
                expected_at = execution_at
            return dict(strategy_id=SID, name="HGB＋对角风险", environment="SIMULATE",
                running=not self.stop_event.is_set(), status=self.status, reason=self.reason,
                last_error=self.last_error, budget=self.budget, account_id=("****" + account_id[-4:]) if account_id != "paper" else None,
                cash=cash, equity=equity, positions=self.snapshot.get("positions", {}), orders=orders,
                order_count=len(orders), next_open_utc=self.metadata.get("next_open_utc"),
                next_expected_open_utc=self.metadata.get("next_expected_open_utc"), plan=self.plan,
                execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds,
                execution_deadline_utc=self._execution_end().isoformat() if execution_at else None,
                buy_order_type="MARKET" if self.allow_partial_quotes else "NORMAL",
                sell_order_type="MARKET" if self.allow_partial_quotes else "NORMAL",
                market_buy_cash_buffer=MARKET_BUY_CASH_BUFFER if self.allow_partial_quotes else None,
                reprice_policy=dict(interval_seconds=REPRICE_INTERVAL_SECONDS,
                                    max_attempts_per_order=MAX_REPRICES_PER_ORDER,
                                    terminal_retry_cooldown_seconds=TERMINAL_RETRY_COOLDOWN_SECONDS,
                                    max_terminal_retries_per_code=MAX_TERMINAL_RETRIES_PER_CODE,
                                    mode="SAME_BROKER_ORDER_ID", enabled=self.allow_partial_quotes),
                allow_partial_quotes=self.allow_partial_quotes, subscription_prewarm=self.prewarm_state,
                skipped=self.engine._get("best_execution", {}).get("skipped", []),
                execution_time_utc=execution_at.isoformat() if execution_at else None,
                next_expected_execution_utc=expected_at.isoformat() if expected_at else None,
                live_enabled=False)

    def close(self):
        self.stop()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=10)
        self.engine.close()
