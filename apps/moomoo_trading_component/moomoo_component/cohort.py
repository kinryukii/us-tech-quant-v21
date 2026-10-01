"""Three isolated USD paper books driven by frozen close -> next-open signals.

There is no broker order path in this class.  DailySource owns data refresh and
model inference; the quote feed owns read-only Moomoo market data.  Engine owns
each book's SQLite fills, cash, positions and durable signal idempotency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
from zoneinfo import ZoneInfo

from .core import Engine
from .locking import DataLock
from .strategy import number, timestamp

STRATEGIES = {
    "RAW_A2": "Raw A2",
    "HGB_DIAG_5": "HGB + 对角风险",
    "HGB_FACTOR_5": "HGB + 因子 / 收缩风险",
}
OPEN_WINDOW_SECONDS = 60
FEE_BPS = 5
NY = ZoneInfo("America/New_York")


def _now(value=None):
    result = value if value is not None else datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("执行时间必须明确时区")
    return result.astimezone(timezone.utc)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class Cohort:
    def __init__(self, runtime_root, source, quote_feed, execution_delay_minutes=None,
                 execution_window_seconds=None, allow_partial_quotes=None):
        if execution_delay_minutes is not None and (
                type(execution_delay_minutes) is not int or not 0 <= execution_delay_minutes <= 180):
            raise ValueError("执行延迟必须是0至180的整数分钟")
        if execution_window_seconds is not None and (
                type(execution_window_seconds) is not int or not 1 <= execution_window_seconds <= 600):
            raise ValueError("执行窗口必须是1至600的整数秒")
        if allow_partial_quotes is not None and type(allow_partial_quotes) is not bool:
            raise ValueError("逐票执行必须是明确布尔值")
        self.path = Path(runtime_root)
        self.path.mkdir(parents=True, exist_ok=True)
        self.data_lock = DataLock(self.path / "cohort.lock")
        self.lock, self.tick_lock = threading.RLock(), threading.Lock()
        self.db = sqlite3.connect(self.path / "cohort.sqlite3", check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events(time TEXT,event TEXT,detail TEXT)")
        self.source, self.quote_feed = source, quote_feed
        self.stop_event = threading.Event()
        self.stop_event.set()
        self.halt_event = threading.Event()
        self.worker, self.best_broker = None, None
        self.closed = False
        self._prewarm_key = None
        self.engines = {}
        try:
            for sid in STRATEGIES:
                self.engines[sid] = Engine(self.path / "books" / sid,
                    quote_provider=quote_feed.quotes, paper_account_id="paper-" + sid, paper_only=True)
        except Exception:
            for engine in self.engines.values():
                engine.close()
            self.db.close()
            self.data_lock.close()
            raise
        saved = self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()
        self.meta = json.loads(saved[0]) if saved else {}
        previous_delay = self.meta.get("execution_delay_minutes", 0)
        delay = previous_delay if execution_delay_minutes is None else execution_delay_minutes
        if type(delay) is not int or not 0 <= delay <= 180:
            for engine in self.engines.values():
                engine.close()
            self.db.close()
            self.data_lock.close()
            raise ValueError("持久执行延迟必须是0至180的整数分钟")
        self.execution_delay_minutes = delay
        prior_window = self.meta.get("execution_window_seconds", OPEN_WINDOW_SECONDS)
        window = prior_window if execution_window_seconds is None else execution_window_seconds
        prior_partial = self.meta.get("allow_partial_quotes", False)
        partial = prior_partial if allow_partial_quotes is None else allow_partial_quotes
        if type(window) is not int or not 1 <= window <= 600 or type(partial) is not bool:
            for engine in self.engines.values():
                engine.close()
            self.db.close()
            self.data_lock.close()
            raise ValueError("持久执行窗口或逐票配置无效")
        self.execution_window_seconds, self.allow_partial_quotes = window, partial
        self.meta.setdefault("execution_time_utc", None)
        self.meta.setdefault("next_expected_execution_utc", None)
        self.meta.update(status="STOPPED", running=False, mode="paper", paper=True,
                         fee_bps=FEE_BPS, initial_cash_per_strategy=10000.0,
                         execution_delay_minutes=delay, execution_window_seconds=window,
                         allow_partial_quotes=partial,
                         reason="等待启动；仅本地纸面记录", last_error="", connection_error="")
        if self.meta.get("halted") or any(e.halt_event.is_set() for e in self.engines.values()):
            self.halt_event.set()
            self.meta.update(status="HALTED", reason="紧急停止已锁定", halted=True)
        self.plans = self.meta.pop("plans", {})
        self.book_status = self.meta.pop("book_status", {})
        for sid, engine in self.engines.items():
            committed = engine.db.execute("SELECT payload FROM paper_batches ORDER BY rowid DESC LIMIT 1").fetchone()
            if committed:
                self.book_status[sid] = json.loads(committed[0])
        self.close_states = self.meta.pop("plan_close_states", {})
        self.plan_metadata = self.meta.pop("plan_metadata", {})
        if self.meta.get("next_open_utc"):
            scheduled = self._scheduled_open(self.meta["next_open_utc"]).isoformat()
            self.meta.update(execution_time_utc=scheduled, next_expected_execution_utc=scheduled)
        if self.plan_metadata.get("next_open_utc"):
            self.plan_metadata.update(execution_time_utc=self._scheduled_open(self.plan_metadata["next_open_utc"]).isoformat(),
                                      execution_delay_minutes=delay, execution_window_seconds=window,
                                      allow_partial_quotes=partial)
        self.loaded_key = None
        self._persist()
        if previous_delay != delay:
            self._event("EXECUTION_SCHEDULE_CHANGED", {"previous_delay_minutes": previous_delay,
                        "execution_delay_minutes": delay, "execution_window_seconds": window,
                        "execution_time_utc": self.meta.get("execution_time_utc")}, _now())
        if prior_window != window or prior_partial != partial:
            self._event("EXECUTION_POLICY_CHANGED", {"previous_window_seconds": prior_window,
                        "execution_window_seconds": window, "previous_allow_partial_quotes": prior_partial,
                        "allow_partial_quotes": partial}, _now())

    def _scheduled_open(self, value):
        return timestamp(value) + timedelta(minutes=self.execution_delay_minutes)

    def _persist(self):
        with self.lock:
            value = {**self.meta, "plans": self.plans, "book_status": self.book_status,
                     "plan_close_states": self.close_states, "plan_metadata": self.plan_metadata}
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",
                            (json.dumps(value, ensure_ascii=False, allow_nan=False),))
            self.db.commit()

    def _event(self, event, detail, now):
        with self.lock:
            self.db.execute("INSERT INTO events VALUES (?,?,?)", (now.isoformat(), event,
                json.dumps(detail, ensure_ascii=False, allow_nan=False)))
            self.db.commit()

    def _hook(self, method, **kwargs):
        if self.best_broker is None:
            return
        try:
            getattr(self.best_broker, method)(**kwargs)
            if method == "start":
                with self.lock:
                    self.meta["broker_error"] = ""
                    self._persist()
        except Exception as exc:
            with self.lock:
                self.meta["broker_error"] = str(exc)

    def start(self):
        with self.lock:
            if self.closed:
                raise ValueError("执行器已关闭")
            if self.halt_event.is_set():
                raise ValueError("紧急停止已锁定，不能自动恢复")
            if self.worker and self.worker.is_alive():
                return self.state()
            for engine in self.engines.values():
                engine.cancel_step.clear()
            self.stop_event.clear()
            self.meta.update(running=True, status="WAITING_SOURCE", reason="等待已完成日信号及计划执行时点")
            self._persist()
            self.worker = threading.Thread(target=self._run, daemon=True, name="applied-paper-cohort")
            self.worker.start()
        self._hook("start")
        return self.state()

    def stop(self):
        self.stop_event.set()  # Abort before waiting for any book or data-source lock.
        for engine in self.engines.values():
            engine.cancel_step.set()
        self._hook("stop")
        with self.lock:
            self.meta.update(running=False, status="HALTED" if self.halt_event.is_set() else "STOPPED",
                             reason="已停止；保留纸面持仓和成交记录")
            if not self.closed:
                self._persist()
        return self.state()

    def halt(self):
        self.halt_event.set()
        self.stop_event.set()
        for engine in self.engines.values():
            engine.halt_event.set()
            engine.cancel_step.set()
        self._hook("halt")
        for engine in self.engines.values():
            with engine.lock:
                engine._halt("三策略本地纸面账户紧急停止")
        with self.lock:
            self.meta.update(running=False, halted=True, status="HALTED", reason="紧急停止已锁定")
            self._persist()
        return self.state()

    def _books_input(self):
        result = {}
        for sid, engine in self.engines.items():
            book = engine.paper_book()
            result[sid] = dict(cash=book["cash"],
                               positions={p["code"]: p["qty"] for p in book["positions"]})
        return result

    def _executed(self, sid, execution):
        status = self.book_status.get(sid, {})
        return status.get("execution_date") == execution and status.get("status") == "EXECUTED"

    def _processed(self, sid, execution):
        row = self.engines[sid].db.execute("SELECT payload FROM paper_batches ORDER BY rowid DESC LIMIT 1").fetchone()
        batch = json.loads(row[0]) if row else {}
        return batch.get("execution_date") == execution and (
            batch.get("status") == "EXECUTED" or bool(batch.get("processed_codes")))

    def _prewarm(self, data, clock, opening):
        session_close = timestamp(data["next_close_utc"])
        # Subscription-only warming is safe before the opening; it supplies no prices.
        if not opening - timedelta(minutes=5) <= clock < min(opening, session_close):
            return
        codes = {row["code"] for plan in self.plans.values() for row in plan.get("rows", []) if row["target_weight"]}
        for engine in self.engines.values():
            codes.update(row["code"] for row in engine.paper_book()["positions"] if row["qty"])
        if not codes:
            return
        key = _fingerprint({"signal_date": data["signal_date"], "execution_date": data["execution_date"],
                            "execution_time_utc": opening.isoformat(), "codes": sorted(codes)})
        previous = self.meta.get("subscription_prewarm", {})
        if self._prewarm_key == key or (previous.get("key") == key and previous.get("status") == "ERROR"
                and clock < timestamp(previous["retry_after_utc"])):
            return
        note = dict(key=key, signal_date=data["signal_date"], execution_date=data["execution_date"],
                    codes=sorted(codes), attempted_at_utc=clock.isoformat(),
                    basis="SUBSCRIPTION_ONLY_NOT_EXECUTABLE_QUOTES")
        if self.stop_event.is_set() or self.halt_event.is_set():
            return
        try:
            self.quote_feed.prewarm(sorted(codes))
            self._prewarm_key = key
            note.update(status="SUBSCRIBED", reason="仅完成证券验证及订阅；正式执行仍需完整行情验证")
        except Exception as exc:
            note.update(status="ERROR", reason=str(exc), retry_after_utc=(clock + timedelta(seconds=30)).isoformat())
        with self.lock:
            self.meta["subscription_prewarm"] = note
        self._event("SUBSCRIPTION_PREWARM", note, clock)

    def _metadata(self, data, now):
        if not isinstance(data, dict):
            raise ValueError("DAILY_SOURCE_METADATA_INVALID")
        signal, execution = data.get("signal_date"), data.get("execution_date")
        opening, close = timestamp(data["next_open_utc"]), timestamp(data["signal_close_utc"])
        if not isinstance(signal, str) or not isinstance(execution, str) or signal >= execution:
            raise ValueError("DAILY_SOURCE_DATE_CONTRACT")
        if opening.astimezone(NY).date().isoformat() != execution or close.astimezone(NY).date().isoformat() != signal:
            raise ValueError("DAILY_SOURCE_SESSION_IDENTITY")
        if close >= opening or close > now:
            raise ValueError("DAILY_SOURCE_FUTURE_SIGNAL")
        return signal, execution, opening

    def _refresh_if_due(self, data, now):
        if data.get("status") in {"READY", "OPEN_WINDOW"} and not data.get("data_gaps"):
            return data
        opening = timestamp(data["next_open_utc"])
        close = timestamp(data["signal_close_utc"])
        session_close = timestamp(data["next_close_utc"])
        # A missed intraday opening cannot be repaired by rolling an old signal.
        if opening + timedelta(seconds=OPEN_WINDOW_SECONDS) <= now < session_close:
            return data
        signal = data["signal_date"]
        not_before = timestamp(data.get("refresh_not_before_utc") or
                               (close + timedelta(seconds=60)).isoformat())
        if now < not_before:
            return data
        attempted = self.meta.get("last_refresh_attempt")
        if close > now or self.meta.get("last_refreshed_signal_date") == signal:
            return data
        if attempted and (now - timestamp(attempted)).total_seconds() < 900:
            return data
        if self.stop_event.is_set() or self.halt_event.is_set():
            return data
        with self.lock:
            self.meta.update(last_refresh_attempt=now.isoformat(), status="REFRESHING",
                             reason="更新已完成市场日；不训练模型")
            self._persist()
        try:
            self.source.refresh()  # DailySource reuses the original single-update lock.
            updated = self.source.status(now=now)
            if updated.get("status") in {"READY", "OPEN_WINDOW"} and not updated.get("data_gaps"):
                self.meta["last_refreshed_signal_date"] = updated["signal_date"]
            self._event("REFRESH", {"signal_date": signal, "status": updated.get("status")}, now)
            return updated
        except Exception as exc:
            self.meta["last_error"] = "DAILY_REFRESH: " + str(exc)
            self._event("REFRESH_ERROR", {"signal_date": signal, "reason": str(exc)}, now)
            return data

    def _prepare(self, data, now):
        signal = data["signal_date"]
        inputs = self._books_input()
        key = (signal, _fingerprint(inputs), _fingerprint(data.get("source_refs", {})))
        if key == self.loaded_key:
            return
        states = self.source.close_states(books=inputs, signal_date=signal)
        if not isinstance(states, dict) or set(states) != set(STRATEGIES):
            raise ValueError("SIGNAL_CLOSE_STATES_INCOMPLETE")
        for sid, state in states.items():
            if state.get("signal_date") != signal or state.get("valuation_basis") != "SIGNAL_CLOSE":
                raise ValueError("SIGNAL_CLOSE_STATE_CLOCK: " + sid)
            weights, cash = state.get("weights"), number(state.get("cash_weight"), "收盘现金权重")
            if not isinstance(weights, dict) or abs(sum(number(w, "收盘持仓权重") for w in weights.values()) + cash - 1) > 1e-8:
                raise ValueError("SIGNAL_CLOSE_STATE_WEIGHTS: " + sid)
            if "equity" in state:
                self.engines[sid].paper_record_close(signal, state)
        loaded = self.source.load(states=states, now=now)
        self._metadata(loaded, now)
        if any(loaded.get(key) != data.get(key) for key in
               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
            raise ValueError("SOURCE_CHANGED_DURING_PLAN")
        plans = loaded.get("plans", {})
        if set(plans) != set(STRATEGIES):
            raise ValueError("THREE_FROZEN_PLANS_REQUIRED")
        if loaded.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}:
            raise ValueError("CURRENT_SOURCE_BLOCKED: " + str(loaded.get("reason", loaded.get("status"))))
        with self.lock:
            for sid, plan in plans.items():
                weights = [number(r.get("target_weight"), "目标权重") for r in plan.get("rows", [])]
                for row in plan.get("rows", []):
                    number(row.get("weight_before"), "收盘持仓权重")
                cash = number(plan.get("target_cash_weight"), "目标现金权重")
                if abs(sum(weights) + cash - 1) > 1e-8:
                    raise ValueError("PLAN_WEIGHTS_NOT_NORMALIZED: " + sid)
            self.plans, self.close_states, self.loaded_key = plans, states, key
            self.plan_metadata = {key: loaded.get(key) for key in ("signal_date", "execution_date",
                "next_open_utc", "signal_close_utc", "source_refs", "source_date")}
            self.plan_metadata.update(execution_time_utc=self._scheduled_open(loaded["next_open_utc"]).isoformat(),
                                      execution_delay_minutes=self.execution_delay_minutes,
                                      execution_window_seconds=self.execution_window_seconds,
                                      allow_partial_quotes=self.allow_partial_quotes)
            self.meta.update(source_refs=loaded.get("source_refs", data.get("source_refs", {})),
                             sourcecutoff=signal, plan_signal_date=signal, plan_execution_date=loaded["execution_date"])
            self._persist()  # Preserve the exact plans before any book commits a fill.

    @staticmethod
    def _fresh_quotes(quotes, now):
        for code, quote in quotes.items():
            age = (now - timestamp(quote["asof"])).total_seconds()
            if not 0 <= age <= 30:
                raise ValueError("真实纸面标价过期或来自未来: " + code)

    def _market_summary(self):
        errors = self.meta.get("book_quote_errors", {})
        self.meta["connection_error"] = "; ".join(f"{sid}: {errors[sid]}" for sid in STRATEGIES if errors.get(sid))
        stamps = self.meta.get("book_quote_asof", {}).values()
        self.meta["quote_asof"] = min(stamps, key=timestamp, default=None)

    def _mark(self, sid, quotes, now):
        self._fresh_quotes(quotes, now)
        engine = self.engines[sid]
        held = {row["code"] for row in engine.paper_book()["positions"] if row["qty"]}
        if not held.issubset(quotes):
            raise ValueError("本账户真实持仓标价不完整")
        date = now.astimezone(NY).date().isoformat()
        engine.paper_mark(quotes, day=date)
        with self.lock:
            self.meta.setdefault("book_quote_errors", {}).pop(sid, None)
            if quotes:
                self.meta.setdefault("book_quote_asof", {})[sid] = min(
                    (q["asof"] for q in quotes.values()), key=timestamp)
                self.meta["quote_source"] = "MOOMOO_OPEND"
            self._market_summary()

    def tick(self, now=None):
        clock = _now(now)
        if self.closed:
            raise ValueError("执行器已关闭")
        if not self.tick_lock.acquire(blocking=False):
            return self.state()
        try:
            self._hook("tick", now=clock)
            data = self.source.status(now=clock)
            self._metadata(data, clock)
            data = self._refresh_if_due(data, clock)
            signal, execution, actual_opening = self._metadata(data, clock)
            opening = self._scheduled_open(data["next_open_utc"])
            with self.lock:
                self.meta.update({key: data.get(key) for key in ("signal_date", "execution_date",
                    "next_open_utc", "signal_close_utc", "next_close_utc", "upcoming_open_utc",
                    "next_refresh_utc", "refresh_not_before_utc", "source_refs", "data_gaps")})
                self.meta["sourcecutoff"] = signal
                upcoming = data.get("next_expected_open_utc") or data.get("upcoming_open_utc") or data["next_open_utc"]
                expected = opening if clock < opening + timedelta(seconds=self.execution_window_seconds) else self._scheduled_open(upcoming)
                self.meta.update(execution_time_utc=opening.isoformat(), next_expected_execution_utc=expected.isoformat(),
                                  execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds)
            if self.stop_event.is_set() or self.halt_event.is_set():
                return self.state()
            if data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}:
                self.meta.update(status="WAITING_SOURCE", reason=data.get("reason", "当前信号未完成"))
                return self.state()
            # Once a signal has executed, its old close cannot revalue new holdings or rerun inference.
            executed = all(self._executed(sid, execution) for sid in STRATEGIES)
            some_executed = any(self._processed(sid, execution) for sid in STRATEGIES)
            if not executed and not some_executed:
                self._prepare(data, clock)
            elif not executed and (self.meta.get("plan_signal_date") != signal or
                                   self.meta.get("plan_execution_date") != execution):
                raise ValueError("已成交部分账户，但该信号冻结计划未完整持久保存")
            if not executed:
                self._prewarm(data, clock, opening)
            if self.stop_event.is_set() or self.halt_event.is_set():
                return self.state()
            if clock >= opening + timedelta(seconds=self.execution_window_seconds) and not executed:
                partial = self.allow_partial_quotes and some_executed
                self.meta.update(status="PARTIALLY_EXECUTED" if partial else "MISSED_OPEN",
                                 reason="本期窗口已结束；保留实际部分成交及未成交目标，不补发" if partial else "已错过该信号的计划执行窗口；不补发该信号")
                if (self.meta.get("last_missed_execution_date") != execution
                        or self.meta.get("last_missed_execution_time_utc") != opening.isoformat()):
                    self.meta.update(last_missed_execution_date=execution, last_missed_execution_time_utc=opening.isoformat())
                    self._event("MISSED_OPEN", dict(signal_date=signal, execution_date=execution,
                        next_open_utc=data["next_open_utc"], execution_time_utc=opening.isoformat(),
                        execution_delay_minutes=self.execution_delay_minutes), clock)
                for sid in STRATEGIES:
                    if not self._executed(sid, execution):
                        previous = self.book_status.get(sid, {})
                        self.book_status[sid] = {**previous, "status": "PARTIALLY_EXECUTED" if self.allow_partial_quotes
                            and self._processed(sid, execution) else "MISSED_OPEN", "execution_date": execution,
                            "signal_date": signal, "reason": "本账户窗口已结束；保留实际成交和未成交原因，不补发"}
            elif clock < opening and not executed:
                self.meta.update(status="WAITING_OPEN", reason="已完成日信号就绪，等待计划执行时点 " + opening.isoformat())
            elif not executed:
                errors = {}
                for sid, engine in self.engines.items():
                    if self.stop_event.is_set() or self.halt_event.is_set():
                        break
                    if self._executed(sid, execution):
                        continue
                    stage = "QUOTES"
                    try:
                        book = engine.paper_book()
                        codes = {row["code"] for row in self.plans[sid]["rows"] if row["target_weight"]}
                        codes.update(row["code"] for row in book["positions"] if row["qty"])
                        if self.stop_event.is_set() or self.halt_event.is_set():
                            break
                        quote_errors = {}
                        if self.allow_partial_quotes:
                            response = self.quote_feed.quotes_partial(sorted(codes)) if codes else {"quotes": {}, "errors": {}}
                            quotes, quote_errors = dict(response["quotes"]), dict(response["errors"])
                        else:
                            quotes = self.quote_feed.quotes(sorted(codes)) if codes else {}
                        if self.stop_event.is_set() or self.halt_event.is_set():
                            break
                        fill_clock = clock if now is not None else _now()
                        if self.allow_partial_quotes:
                            for code, quote in list(quotes.items()):
                                try:
                                    self._fresh_quotes({code: quote}, fill_clock)
                                except Exception as exc:
                                    quote_errors[code] = str(exc)
                                    quotes.pop(code)
                        else:
                            self._fresh_quotes(quotes, fill_clock)
                        self.meta.setdefault("book_quote_errors", {}).pop(sid, None)
                        stage = "REBALANCE"
                        options = dict(execution_window_seconds=self.execution_window_seconds)
                        if self.allow_partial_quotes:
                            options.update(allow_partial_quotes=True, quote_errors=quote_errors)
                        result = engine.paper_rebalance(sid, self.plans[sid], quotes, now=fill_clock,
                            next_open_utc=self.plan_metadata["execution_time_utc"], signal_date=signal, execution_date=execution,
                            signal_close_utc=self.plan_metadata["signal_close_utc"], source_refs=self.plan_metadata.get("source_refs"),
                            fee_bps=FEE_BPS, **options)
                        self.book_status[sid] = result
                        if result.get("skipped"):
                            errors[sid] = "; ".join(str(row["code"]) + ": " + str(row["reason"]) for row in result["skipped"])
                        self._persist()  # Each SQLite book is independently idempotent across a crash.
                    except Exception as exc:
                        if self.stop_event.is_set() or self.halt_event.is_set():
                            break
                        errors[sid] = str(exc)
                        self.book_status[sid] = dict(status="BLOCKED", signal_date=signal,
                            execution_date=execution, reason=str(exc), failure_stage=stage)
                        if stage == "QUOTES":
                            self.meta.setdefault("book_quote_errors", {})[sid] = str(exc)
                        self._persist()
                        continue
                    if self.stop_event.is_set() or self.halt_event.is_set():
                        break
                    try:
                        held = {row["code"] for row in engine.paper_book()["positions"] if row["qty"]}
                        if held.issubset(quotes):
                            self._mark(sid, quotes, fill_clock)
                        if self.allow_partial_quotes and errors.get(sid):
                            self.meta.setdefault("book_quote_errors", {})[sid] = errors[sid]
                    except Exception as exc:
                        self.meta.setdefault("book_quote_errors", {})[sid] = str(exc)
                if self.stop_event.is_set() or self.halt_event.is_set():
                    return self.state()
                self._market_summary()
                completed = [sid for sid in STRATEGIES if self._executed(sid, execution)]
                if len(completed) == len(STRATEGIES):
                    self.meta.update(status="EXECUTED", reason="三套独立账户已按计划窗口真实行情记入纸面成交",
                                     last_error=self.meta["connection_error"])
                else:
                    details = "; ".join(f"{sid}: {errors[sid]}" for sid in STRATEGIES if sid in errors)
                    partial = self.allow_partial_quotes and any(self._processed(sid, execution) for sid in STRATEGIES)
                    self.meta.update(status="PARTIALLY_EXECUTED" if partial else "BLOCKED", last_error=details,
                        reason="已执行账户：" + (", ".join(completed) or "无") + "；受阻账户：" + details)
            else:
                self.meta.update(status="EXECUTED", reason="本信号已处理；等待下一完成日")
            # Mark held positions only during the source's actual regular session.
            if not (opening <= clock < opening + timedelta(seconds=self.execution_window_seconds)):
                close = timestamp(data["next_close_utc"])
                if actual_opening <= clock < close:
                    for sid, engine in self.engines.items():
                        if self.stop_event.is_set() or self.halt_event.is_set():
                            break
                        held = sorted(row["code"] for row in engine.paper_book()["positions"] if row["qty"])
                        if not held:
                            day = clock.astimezone(NY).date().isoformat()
                            with engine.lock:
                                if engine.db.execute("SELECT 1 FROM paper_nav WHERE day=?", (day,)).fetchone() is None:
                                    engine.paper_mark({}, day=day, basis="CASH_LEDGER")
                            continue
                        if self.stop_event.is_set() or self.halt_event.is_set():
                            break
                        try:
                            quotes = self.quote_feed.quotes(held)
                            if self.stop_event.is_set() or self.halt_event.is_set():
                                break
                            self._mark(sid, quotes, clock if now is not None else _now())
                        except Exception as exc:
                            self.meta.setdefault("book_quote_errors", {})[sid] = str(exc)
                    self._market_summary()
                    if self.meta["connection_error"]:
                        self.meta.update(last_error=self.meta["connection_error"])
                    else:
                        self.meta["last_error"] = ""
            return self.state()
        except Exception as exc:
            with self.lock:
                self.meta.update(status="BLOCKED", reason=str(exc), last_error=str(exc),
                    data_gaps=getattr(exc, "data_gaps", self.meta.get("data_gaps", [])))
            return self.state()
        finally:
            if not self.closed:
                self._persist()
            self.tick_lock.release()

    def _poll_delay(self, now=None):
        clock = _now(now)
        opening = self.meta.get("execution_time_utc")
        if opening:
            seconds = (timestamp(opening) - clock).total_seconds()
            if 0 < seconds <= 30:
                return max(.05, min(1.0, seconds))
            if -self.execution_window_seconds < seconds <= 0:
                return 1.0
        return 30.0

    def _run(self):
        while not self.stop_event.is_set():
            self.tick()
            if self.stop_event.wait(self._poll_delay()):
                break

    def trades(self):
        return sorted((trade for engine in self.engines.values() for trade in engine.paper_trades()),
                      key=lambda r: (r["filled_at"], r["strategy_id"], r["sequence"]))

    def state(self):
        with self.lock:
            result = {**self.meta, "running": not self.stop_event.is_set(),
                      "halted": self.halt_event.is_set(), "books": {}}
            for sid, engine in self.engines.items():
                book = engine.paper_book()
                plan = self.plans.get(sid)
                weights = {row["code"]: row["target_weight"] for row in plan.get("rows", [])} if plan else {}
                before = {row["code"]: row.get("weight_before") for row in plan.get("rows", [])} if plan else {}
                if plan:
                    for position in book["positions"]:
                        code = position["code"]
                        weights.setdefault(code, 0)
                        before.setdefault(code, self.close_states.get(sid, {}).get("weights", {}).get(code[3:], 0))
                actions = [dict(code=code, ticker=code.removeprefix("US."), target_weight=weight,
                    weight_before=before.get(code), action=("BUY" if weight > before.get(code, 0) + 1e-10
                    else "SELL" if weight < before.get(code, 0) - 1e-10 else "HOLD")) for code, weight in weights.items()]
                result["books"][sid] = {**book, "strategy_id": sid, "name": STRATEGIES[sid],
                    "plan": plan, "planned_actions": actions, "status": self.book_status.get(sid, {}).get("status", result["status"]),
                    "execution": self.book_status.get(sid), "trades": engine.paper_trades(limit=100),
                    "nav_history": engine.paper_nav_history(), "fee_bps": FEE_BPS,
                    "plan_metadata": self.plan_metadata, "close_state": self.close_states.get(sid),
                    "connection_error": self.meta.get("book_quote_errors", {}).get(sid, ""),
                    "quote_asof": self.meta.get("book_quote_asof", {}).get(sid),
                    "reason": self.book_status.get(sid, {}).get("reason") or self.meta.get("book_quote_errors", {}).get(sid, "")}
                if result["status"] == "WAITING_OPEN" and not self._executed(sid, self.meta.get("execution_date")):
                    result["books"][sid].update(status="WAITING_OPEN", reason=result["reason"])
            result["trades"] = sorted((trade for book in result["books"].values() for trade in book["trades"]),
                key=lambda r: (r["filled_at"], r["strategy_id"], r["sequence"]))[-100:]
            if self.best_broker is not None:
                try:
                    result["broker"] = self.best_broker.state()
                except Exception as exc:
                    result["broker"] = dict(status="ERROR", last_error=str(exc))
            return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))

    def close(self):
        if self.closed:
            return
        self.stop()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=5)
        if self.worker and self.worker.is_alive():
            raise RuntimeError("数据刷新仍在完成；已停止执行，待刷新结束再关闭账本")
        self._hook("close")
        with self.lock:
            for engine in self.engines.values():
                engine.close()
            close = getattr(self.quote_feed, "close", None)
            if close:
                close()
            self.db.close()
            self.data_lock.close()
            self.closed = True
