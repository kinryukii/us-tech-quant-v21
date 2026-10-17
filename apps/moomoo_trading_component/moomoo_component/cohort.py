"""Isolated USD paper books driven by frozen close -> next-open signals.

There is no broker order path in this class.  DailySource owns data refresh and
model inference; the quote feed owns read-only Moomoo market data.  Engine owns
each book's SQLite fills, cash, positions and durable signal idempotency.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
from contextlib import closing, ExitStack, contextmanager, nullcontext
import hashlib
import json
import re
from pathlib import Path
import sqlite3
import threading
import time
from zoneinfo import ZoneInfo

from .core import Engine, TERMINAL, _first_execution_sha, _first_continuation_end
from .locking import DataLock
from .applied_source import _reset_request, _bytes, _worker_quarantine_reason
from .strategy import (number, timestamp, code_valid, validate_auto_completion_policy,
    ACTIVE_PAPER_STRATEGY_IDS, LEGACY_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS, APPLIED_STRATEGY_NAMES, exact_hold_units, requested_gross_input, accepted_requested_gross_state, automatic_completion_clock_matches)

from .showcase import (load_roster_reference, validate_roster_binding, accepted_roster_projection)

# Public legacy alias keeps historical callers stable; strategy.py owns identities.
STRATEGIES = {sid: APPLIED_STRATEGY_NAMES[sid] for sid in LEGACY_PAPER_STRATEGY_IDS}
HGB_STRATEGIES = ("HGB_DIAG_5", "HGB_FACTOR_5")
OPEN_WINDOW_SECONDS = 60
FEE_BPS = 5
NY = ZoneInfo("America/New_York")


def _now(value=None):
    result = value if value is not None else datetime.now(timezone.utc)
    if not isinstance(result, datetime) or result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("执行时间必须明确时区")
    return result.astimezone(timezone.utc)


@contextmanager
def _manual_inference_update(owner, source):
    """Use the original cross-process daily lock only for explicit model loads."""
    from scripts.common.daily_support import single_update
    daily = getattr(source, "daily_root", None)
    paths = getattr(source, "paths", None)
    configured = getattr(paths, "daily_root", None)
    if daily is None:
        daily = configured
    if daily is None or configured is not None and Path(daily).resolve() != Path(configured).resolve():
        raise ValueError("MANUAL_MODEL_UPDATE_ORIGINAL_DAILY_ROOT_REQUIRED")
    if getattr(owner, "_manual_inference_quarantine_lock", None) is not None:
        raise RuntimeError("MANUAL_MODEL_UPDATE_CLEANUP_UNVERIFIED")
    guard = single_update(Path(daily) / "A2_today_recommendation")
    guard.__enter__()  # Original OS nonblocking byte lock; no retry or second lease.
    try:
        yield
    finally:
        if _worker_quarantine_reason():
            # A returned protocol error cannot prove the owned child was reaped.
            # Retain the original context/handle, matching the existing sticky owner.
            owner._manual_inference_quarantine_lock = guard
        else:
            guard.__exit__(None, None, None)


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class Cohort:
    def __init__(self, runtime_root, source, quote_feed, execution_delay_minutes=None,
                 execution_window_seconds=None, allow_partial_quotes=None, *, manual_data_updates=False):
        if execution_delay_minutes is not None and (
                type(execution_delay_minutes) is not int or not 0 <= execution_delay_minutes <= 180):
            raise ValueError("执行延迟必须是0至180的整数分钟")
        if execution_window_seconds is not None and (
                type(execution_window_seconds) is not int
                or not (1 <= execution_window_seconds <= 600 or execution_window_seconds == 1500)
                or execution_window_seconds == 1500 and execution_delay_minutes not in (None, 25)):
            raise ValueError("执行窗口须为1至600秒；25分钟延迟另支持1500秒")
        if allow_partial_quotes is not None and type(allow_partial_quotes) is not bool:
            raise ValueError("逐票执行必须是明确布尔值")
        if type(manual_data_updates) is not bool:
            raise ValueError("MANUAL_DATA_UPDATES_MODE_INVALID")
        self.manual_data_updates = manual_data_updates
        self.path = Path(runtime_root)
        self.path.mkdir(parents=True, exist_ok=True)
        self.data_lock = DataLock(self.path / "cohort.lock")
        self.lock, self.tick_lock = threading.RLock(), threading.Lock()
        self._maintenance_lock = threading.RLock()
        self._maintenance = None
        self._maintenance_restore_thread = None
        self._maintenance_stopping_thread = None
        # CPython #118172: bypass statement-cache races on this shared connection.
        self.db = sqlite3.connect(self.path / "cohort.sqlite3", check_same_thread=False, cached_statements=0)
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
        self._closing = False
        self._prewarm_key = None
        self.engines = {}
        saved = self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()
        self.meta = json.loads(saved[0]) if saved else {}
        self.plans = self.meta.pop("plans", {})
        self.book_status = self.meta.pop("book_status", {})
        self.close_states = self.meta.pop("plan_close_states", {})
        self.plan_metadata = self.meta.pop("plan_metadata", {})
        try:
            pending = self.meta.get("paper_reset")
            if pending and pending.get("phase") != "COMMITTED":
                self._archive_reset_books(pending)
            roster = self.meta.get("showcase_roster_binding")
            if roster is not None:
                checked = load_roster_reference(roster["roster_ref"], paths=getattr(source, "paths", None))
                if checked["manifest"] != roster["manifest"]:
                    raise ValueError("SHOWCASE_ROSTER_ACCEPTED_MANIFEST_CHANGED")
            self._active_ids()
            retained = roster["retained_book_ids"] if roster is not None else ()
            for sid in dict.fromkeys((*STRATEGIES, *retained, *self._active_ids())):
                self.engines[sid] = Engine(self.path / "books" / sid,
                    quote_provider=quote_feed.quotes, paper_account_id="paper-" + sid, paper_only=True,
                    paper_inception_utc=self._roster_book_inception(sid) if roster is not None else None)
            pending = self.meta.get("paper_reset")
            if pending and pending.get("phase") != "COMMITTED":
                self._finish_hgb_reset(pending)
            self._bind_automatic_completion_policy()
            self._active_ids()
        except Exception:
            for engine in self.engines.values():
                engine.close()
            self.db.close()
            self.data_lock.close()
            raise
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
        if type(window) is not int or not (1 <= window <= 600 or window == 1500 and delay == 25) or type(partial) is not bool:
            for engine in self.engines.values():
                engine.close()
            self.db.close()
            self.data_lock.close()
            raise ValueError("持久执行窗口或逐票配置无效")
        deferred_clock_event = None
        if ((delay, window) == (25, 1500) and (previous_delay, prior_window) != (delay, window)
                and (signal := self._ordinary_clock_signal_to_preserve()) is not None):
            pending = dict(after_signal_date=signal, previous_delay_minutes=previous_delay,
                previous_window_seconds=prior_window, execution_delay_minutes=25, execution_window_seconds=1500)
            if self.meta.get("next_ordinary_execution_clock") != pending:
                self.meta["next_ordinary_execution_clock"] = pending
                deferred_clock_event = ("ORDINARY_EXECUTION_CLOCK_DEFERRED", pending, _now())
            delay, window = previous_delay, prior_window
            self.execution_delay_minutes = delay
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
        for sid, engine in self.engines.items():
            committed = engine.db.execute("SELECT payload FROM paper_batches ORDER BY rowid DESC LIMIT 1").fetchone()
            if committed:
                self.book_status[sid] = json.loads(committed[0])
        preserve_manual_clock = (delay == 30 or self.meta.get("next_ordinary_execution_clock") is not None) and self._manual_schedule_bound(self.plan_metadata)
        if self.meta.get("next_open_utc") and not preserve_manual_clock:
            scheduled = self._scheduled_open(self.meta["next_open_utc"]).isoformat()
            self.meta.update(execution_time_utc=scheduled, next_expected_execution_utc=scheduled)
        if self.plan_metadata.get("next_open_utc") and not preserve_manual_clock:
            scheduled = self._scheduled_open(self.plan_metadata["next_open_utc"])
            exact_time = self.plan_metadata.get("execution_time_utc")
            # An unchanged frozen plan keeps its original UTC spelling on restart.
            # Only a real policy/instant change computes a new scheduled value.
            preserve_time = (isinstance(exact_time, str)
                and self.plan_metadata.get("execution_delay_minutes") == delay
                and self.plan_metadata.get("execution_window_seconds") == window
                and self.plan_metadata.get("allow_partial_quotes") is partial
                and timestamp(exact_time) == scheduled)
            self.plan_metadata.update(execution_time_utc=exact_time if preserve_time else scheduled.isoformat(),
                                      execution_delay_minutes=delay, execution_window_seconds=window,
                                      allow_partial_quotes=partial)
        self.loaded_key = None
        self._persist(event=deferred_clock_event)
        if previous_delay != delay:
            self._event("EXECUTION_SCHEDULE_CHANGED", {"previous_delay_minutes": previous_delay,
                        "execution_delay_minutes": delay, "execution_window_seconds": window,
                        "execution_time_utc": self.meta.get("execution_time_utc")}, _now())
        if prior_window != window or prior_partial != partial:
            self._event("EXECUTION_POLICY_CHANGED", {"previous_window_seconds": prior_window,
                        "execution_window_seconds": window, "previous_allow_partial_quotes": prior_partial,
                        "allow_partial_quotes": partial}, _now())

    def _active_ids(self):
        ids = self.meta.get("active_strategy_ids", list(STRATEGIES))
        binding = self.meta.get("showcase_roster_binding")
        if binding is None:
            return self._legacy_active_ids(ids)
        binding = validate_roster_binding(binding)
        if (self.meta.get("strategy_membership_binding") is None
                or _fingerprint(self.meta["strategy_membership_binding"]) != binding["legacy_membership_binding_sha256"]):
            raise ValueError("SHOWCASE_ROSTER_ORIGINAL_V1_BINDING_CHANGED")
        self._legacy_active_ids(binding["legacy_active_strategy_ids"])
        if ids != binding["manifest"]["showcase_ids"]:
            raise ValueError("SHOWCASE_ROSTER_ACTIVE_IDS_CHANGED")
        rows = self.db.execute("SELECT detail FROM events WHERE event='SHOWCASE_ROSTER_REVISED' ORDER BY rowid")
        previous, seen = None, set()
        for number, row in enumerate(rows, 1):
            current = validate_roster_binding(json.loads(row[0]))
            rid = current["manifest"]["revision_id"]
            if (current["revision_number"] != number or rid in seen
                    or current["previous_binding_sha256"] != (_fingerprint(previous) if previous else None)
                    or previous is not None and (
                        current["legacy_membership_binding_sha256"] != previous["legacy_membership_binding_sha256"]
                        or current["legacy_active_strategy_ids"] != previous["legacy_active_strategy_ids"]
                        or not set(previous["retained_book_ids"]) <= set(current["retained_book_ids"]))):
                raise ValueError("SHOWCASE_ROSTER_AUDIT_CHAIN_CHANGED")
            seen.add(rid)
            previous = current
        if previous != binding:
            raise ValueError("SHOWCASE_ROSTER_AUDIT_MISSING")
        return tuple(ids)

    def _legacy_active_ids(self, ids):
        if (not isinstance(ids, list) or not ids or len(ids) != len(set(ids))
                or set(ids) - set(APPLIED_STRATEGY_NAMES)):
            raise ValueError("ACTIVE_PAPER_STRATEGY_IDS_INVALID")
        reset = self.meta.get("paper_reset")
        binding = self.meta.get("strategy_membership_binding")
        if binding is not None:
            if (binding.get("target_strategy_ids") != list(ACTIVE_PAPER_STRATEGY_IDS)
                    or ids != binding["target_strategy_ids"]
                    or binding.get("prior_paper_reset_sha256") != _fingerprint(reset)
                    or not isinstance(binding.get("preserved_cohort_setting"), str)
                    or hashlib.sha256(binding["preserved_cohort_setting"].encode("utf-8")).hexdigest() != binding.get("preserved_cohort_setting_sha256")):
                raise ValueError("STRATEGY_MEMBERSHIP_BINDING_CHANGED")
            rows = self.db.execute("SELECT detail FROM events WHERE event='STRATEGY_MEMBERSHIP_BOUND'")
            if not any(json.loads(row[0]) == binding for row in rows):
                raise ValueError("STRATEGY_MEMBERSHIP_AUDIT_MISSING")
        elif reset and reset.get("phase") == "COMMITTED" and set(ids) != set(HGB_STRATEGIES):
            raise ValueError("HGB_RESET_ACTIVE_STRATEGIES_CHANGED")
        order = ACTIVE_PAPER_STRATEGY_IDS if binding else tuple(STRATEGIES)
        return tuple(sid for sid in order if sid in ids)

    def _roster_precondition(self):
        return _fingerprint({"membership": self._membership_precondition(),
            "showcase_roster_binding": self.meta.get("showcase_roster_binding")})

    def showcase_roster_state(self):
        """Read only accepted roster metadata; never opens books or reads other owners."""
        with self.lock:
            active_ids = list(self._active_ids())
            result = dict(books={}, metadata_only=True, active_strategy_ids=active_ids,
                **accepted_roster_projection(self.meta))
            binding = self.meta.get("showcase_roster_binding")
            if binding is not None:
                result["showcase_roster_binding"] = deepcopy(binding)
            # Reserve the HTTP envelope/spacing within the separate 64KiB read cap.
            if len(_bytes(result)) > 60 * 1024:
                raise ValueError("SHOWCASE_ROSTER_METADATA_RESPONSE_LIMIT")
            return result

    def preview_showcase_roster(self, *, roster_ref, now=None):
        clock = _now(now)
        checked = load_roster_reference(roster_ref, paths=getattr(self.source, "paths", None), now=clock)
        with self.lock:
            ids = checked["manifest"]["showcase_ids"]
            return dict(showcase_ids=list(ids), roster_ref=checked["roster_ref"],
                roster_precondition_sha256=self._roster_precondition(),
                inactive_queryable_ids=[sid for sid in QUERYABLE_STRATEGY_IDS if sid not in ids],
                paper_only=True, broker_permission_granted=False, models_loaded=0, orders_submitted=0)

    def _showcase_roster_receipt(self, binding, *, idempotent):
        """Bounded control acknowledgement; account histories stay on the GET owner."""
        projection = accepted_roster_projection({"showcase_roster_binding": binding})
        books = {}
        for sid in binding["created_book_ids"]:
            engine = self.engines.get(sid)
            current = self.book_status.get(sid, {})
            status = current.get("status")
            reason = current.get("reason")
            books[sid] = dict(
                status=status[:64] if isinstance(status, str) and engine is not None else "BLOCKED",
                reason=(reason[:512] if isinstance(reason, str) else "SHOWCASE_ROSTER_SOURCE_NOT_PREPARED")
                    if engine is not None else "SHOWCASE_ROSTER_BOOK_OWNER_OPEN_REQUIRED",
                inception_utc=engine.paper_inception_utc if engine is not None else self._roster_book_inception(sid),
                book_owner_ready=engine is not None)
        receipt = dict(action="SHOWCASE_ROSTER_REVISION", status="ACCEPTED", idempotent=idempotent,
            accepted_at_utc=binding["accepted_at_utc"], new_books=books,
            paper_only=True, broker_permission_granted=False, models_loaded=0, orders_submitted=0, **projection)
        if len(_bytes(receipt)) > 65536:
            raise ValueError("SHOWCASE_ROSTER_CONTROL_RECEIPT_TOO_LARGE")
        return receipt

    def _roster_book_inception(self, sid):
        rows = self.db.execute("SELECT detail FROM events WHERE event='SHOWCASE_ROSTER_REVISED' ORDER BY rowid")
        for row in rows:
            binding = json.loads(row[0])
            if sid in binding["created_book_ids"]:
                return binding["accepted_at_utc"]
        return None

    def _open_accepted_roster_books(self, binding):
        # Only an already committed custody event may create/recover a new book.
        for sid in binding["retained_book_ids"]:
            if sid in self.engines:
                continue
            inception = self._roster_book_inception(sid)
            if inception is None:
                raise ValueError("SHOWCASE_ROSTER_RETAINED_BOOK_OWNER_MISSING")
            engine = Engine(self.path / "books" / sid, quote_provider=self.quote_feed.quotes,
                paper_account_id="paper-" + sid, paper_only=True, paper_inception_utc=inception)
            engine.automatic_completion_policy_provider = self._current_automatic_completion_policy
            self.engines[sid] = engine

    def revise_showcase_roster(self, *, roster_ref, expected_precondition_sha256, now=None):
        """Explicit stopped-owner revision; preserves books and all broker permissions."""
        clock = _now(now)
        if not isinstance(expected_precondition_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_precondition_sha256):
            raise ValueError("SHOWCASE_ROSTER_PRECONDITION_REQUIRED")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("SHOWCASE_ROSTER_WAIT_FOR_TICK")
        try:
            with self.lock:
                if (self.closed or self._closing or self.halt_event.is_set() or not self.stop_event.is_set()
                        or self.worker and self.worker.is_alive() or self._maintenance_active()):
                    raise ValueError("SHOWCASE_ROSTER_REQUIRES_STOPPED")
                self._pending_repair_guard()
                if self.meta.get("strategy_membership_binding") is None:
                    raise ValueError("SHOWCASE_ROSTER_ORIGINAL_V1_BINDING_REQUIRED")
                for engine in self.engines.values():
                    engine._require_stopped()
                    if engine._pending():
                        raise ValueError("SHOWCASE_ROSTER_PENDING_ORDER")
                if self.meta.get("paper_reset") and self.meta["paper_reset"].get("phase") != "COMMITTED":
                    raise ValueError("SHOWCASE_ROSTER_PENDING_RESET")
                checked = load_roster_reference(roster_ref, paths=getattr(self.source, "paths", None), now=clock)
                old_ids = list(self._active_ids())
                prior = self.meta.get("showcase_roster_binding")
                if prior is not None and checked["roster_ref"] == prior["roster_ref"]:
                    if checked["manifest"] != prior["manifest"]:
                        raise ValueError("SHOWCASE_ROSTER_ACCEPTED_MANIFEST_CHANGED")
                    self._open_accepted_roster_books(prior)
                    return self._showcase_roster_receipt(prior, idempotent=True)
                if expected_precondition_sha256 != self._roster_precondition():
                    raise ValueError("SHOWCASE_ROSTER_PRECONDITION_CHANGED")
                if prior is not None and not set(prior["retained_book_ids"]) <= set(self.engines):
                    raise ValueError("SHOWCASE_ROSTER_ACCEPTED_BOOK_OPEN_REQUIRED")
                if prior is not None and timestamp(checked["manifest"]["effective_at_utc"]) < timestamp(prior["accepted_at_utc"]):
                    raise ValueError("SHOWCASE_ROSTER_EFFECTIVE_TIME_REGRESSED")
                rows = self.db.execute("SELECT detail FROM events WHERE event='SHOWCASE_ROSTER_REVISED'")
                if any(json.loads(row[0])["manifest"]["revision_id"] == checked["manifest"]["revision_id"] for row in rows):
                    raise ValueError("SHOWCASE_ROSTER_REVISION_ID_REUSED")
                ids = checked["manifest"]["showcase_ids"]
                created_ids = [sid for sid in ids if sid not in self.engines]
                for sid in created_ids:
                    if (self.path / "books" / sid).exists():
                        raise ValueError("SHOWCASE_ROSTER_UNBOUND_BOOK_PATH_EXISTS")
                binding = dict(schema_version=1, revision_number=prior["revision_number"]+1 if prior else 1,
                    roster_ref=checked["roster_ref"], manifest=checked["manifest"], accepted_at_utc=clock.isoformat(),
                    previous_binding_sha256=_fingerprint(prior) if prior else None,
                    legacy_membership_binding_sha256=_fingerprint(self.meta["strategy_membership_binding"]),
                    legacy_active_strategy_ids=prior["legacy_active_strategy_ids"] if prior else old_ids,
                    retained_book_ids=list(dict.fromkeys((*self.engines, *created_ids))), created_book_ids=created_ids)
                next_meta = deepcopy(self.meta)
                next_meta.update(active_strategy_ids=list(ids), showcase_roster_binding=binding,
                    running=False, status="STOPPED")
                next_meta.setdefault("book_plan_metadata", {}).update(
                    {sid: deepcopy(self.meta.get("book_plan_metadata", {}).get(sid, self.plan_metadata)) for sid in self.plans})
                next_meta.setdefault("inactive_plan_metadata", {}).update(
                    {sid: deepcopy(self.meta.get("book_plan_metadata", {}).get(sid, self.plan_metadata))
                     for sid in self.engines if sid not in ids})
                statuses = deepcopy(self.book_status)
                for sid in set(ids) - set(old_ids):
                    statuses[sid] = dict(status="BLOCKED", reason="SHOWCASE_ROSTER_SOURCE_NOT_PREPARED",
                        orders_submitted=0, models_loaded=0)
                value = {**next_meta, "plans": self.plans, "book_status": statuses,
                    "plan_close_states": self.close_states, "plan_metadata": self.plan_metadata}
                # A failed commit creates no filesystem book. Once committed, the
                # same ref or a restart can recover its book at this accepted clock.
                with self.db:
                    self.db.execute("INSERT INTO events VALUES (?,?,?)", (clock.isoformat(),
                        "SHOWCASE_ROSTER_REVISED", json.dumps(binding, ensure_ascii=False, allow_nan=False)))
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",
                        (json.dumps(value, ensure_ascii=False, allow_nan=False),))
                self.meta, self.book_status = next_meta, statuses
                self.loaded_key = None
                self._open_accepted_roster_books(binding)
                return self._showcase_roster_receipt(binding, idempotent=False)
        finally:
            self.tick_lock.release()

    def _active_engines(self):
        ids = self._active_ids()
        if not set(ids) <= set(self.engines):
            raise ValueError("SHOWCASE_ROSTER_BOOK_OWNER_OPEN_REQUIRED")
        return {sid: self.engines[sid] for sid in ids}

    def _membership_precondition(self):
        return _fingerprint({"active_strategy_ids": list(self._active_ids()),
            "paper_reset": self.meta.get("paper_reset"), "plans": self.plans,
            "plan_metadata": self.plan_metadata,
            "automatic_completion_policy": self.meta.get("automatic_completion_policy")})

    def migrate_strategy_membership(self, *, migration_id, requested_at,
            expected_precondition_sha256, target_strategy_ids, now=None):
        """Bind the authorized five books without replacing an existing cash epoch."""
        clock = _now(now)
        if (not isinstance(migration_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", migration_id)
                or timestamp(requested_at) > clock
                or target_strategy_ids != list(ACTIVE_PAPER_STRATEGY_IDS)
                or not re.fullmatch(r"[0-9a-f]{64}", str(expected_precondition_sha256))):
            raise ValueError("STRATEGY_MEMBERSHIP_REQUEST_INVALID")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("STRATEGY_MEMBERSHIP_WAIT_FOR_TICK")
        try:
            with self.lock:
                prior = self.meta.get("strategy_membership_binding")
                if prior is not None:
                    if (prior["migration_id"] == migration_id and prior["requested_at"] == requested_at
                            and prior["expected_precondition_sha256"] == expected_precondition_sha256
                            and prior["target_strategy_ids"] == target_strategy_ids):
                        self._active_ids()
                        return self.state()
                    raise ValueError("STRATEGY_MEMBERSHIP_ALREADY_BOUND")
                if (self.closed or self.halt_event.is_set() or not self.stop_event.is_set()
                        or self.worker and self.worker.is_alive()):
                    raise ValueError("STRATEGY_MEMBERSHIP_REQUIRES_STOPPED")
                self._pending_repair_guard()
                if expected_precondition_sha256 != self._membership_precondition():
                    raise ValueError("STRATEGY_MEMBERSHIP_PRECONDITION_CHANGED")
                for engine in self.engines.values():
                    engine._require_stopped()
                    if engine._pending():
                        raise ValueError("STRATEGY_MEMBERSHIP_PENDING_ORDER")
                reset = self.meta.get("paper_reset")
                if reset and reset.get("phase") != "COMMITTED":
                    raise ValueError("STRATEGY_MEMBERSHIP_PENDING_RESET")
                old_ids = list(self._active_ids())
                created = {}
                try:
                    for sid in target_strategy_ids:
                        if sid not in self.engines:
                            created[sid] = Engine(self.path / "books" / sid,
                                quote_provider=self.quote_feed.quotes,
                                paper_account_id="paper-" + sid, paper_only=True)
                    saved_control = self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0]
                    repair_row = self.db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
                    binding = dict(schema_version=1, migration_id=migration_id, requested_at=requested_at,
                        bound_at_utc=clock.isoformat(), expected_precondition_sha256=expected_precondition_sha256,
                        previous_active_strategy_ids=old_ids, target_strategy_ids=list(target_strategy_ids),
                        prior_paper_reset_sha256=_fingerprint(reset),
                        prior_pending_plan_repair=json.loads(repair_row[0]) if repair_row else None,
                        preserved_cohort_setting=saved_control,
                        preserved_cohort_setting_sha256=hashlib.sha256(saved_control.encode("utf-8")).hexdigest(),
                        prior_automatic_completion_policy_sha256=_fingerprint(self.meta.get("automatic_completion_policy")),
                        preserved_legacy_strategy_ids=["HGB_FACTOR_5"],
                        preserved_book_paths={sid: str(engine.path) for sid, engine in self.engines.items()})
                    next_meta = deepcopy(self.meta)
                    next_meta.update(active_strategy_ids=list(target_strategy_ids),
                        strategy_membership_binding=binding, running=False, status="STOPPED")
                    next_meta.setdefault("book_plan_metadata", {}).update(
                        {sid: deepcopy(self.plan_metadata) for sid in self.plans})
                    next_meta.setdefault("inactive_plan_metadata", {}).update(
                        {sid: deepcopy(self.plan_metadata) for sid in self.engines if sid not in target_strategy_ids})
                    value = {**next_meta, "plans": self.plans, "book_status": self.book_status,
                        "plan_close_states": self.close_states, "plan_metadata": self.plan_metadata}
                    with self.db:
                        self.db.execute("INSERT INTO events VALUES (?,?,?)", (clock.isoformat(),
                            "STRATEGY_MEMBERSHIP_BOUND", json.dumps(binding, ensure_ascii=False, allow_nan=False)))
                        self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",
                            (json.dumps(value, ensure_ascii=False, allow_nan=False),))
                    self.meta = next_meta
                    self.engines.update(created)
                    self.loaded_key = None
                    self._bind_automatic_completion_policy()
                except Exception:
                    for engine in created.values():
                        engine.close()
                    raise
                return self.state()
        finally:
            self.tick_lock.release()

    def _requested_input(self, sid, signal):
        saved = self.meta.get("strategy_requested_state", {}).get(sid, {})
        return requested_gross_input(saved, signal)

    def _ordinary_clock_signal_to_preserve(self):
        today = _now().astimezone(NY).date().isoformat()
        frozen_rows = [self.plan_metadata, *self.meta.get("book_plan_metadata", {}).values()]
        protected = []
        for frozen in frozen_rows:
            signal = frozen.get("signal_date")
            if not signal:
                continue
            bound = self._manual_schedule_bound(frozen)
            if not bound and frozen.get("execution_date", "") > today:
                try:
                    for engine in self._active_engines().values():
                        engine._paper_first_no_attempt(frozen)
                except ValueError:
                    bound = True
            else:
                bound = True
            if bound:
                protected.append(signal)
        return max(protected) if protected else None

    def _next_ordinary_clock(self, data, clock, *, explicit_update=False, maintenance_projection=False):
        record = self.meta.get("next_ordinary_execution_clock")
        if record is None or self.manual_data_updates and not explicit_update:
            return
        expected = {"after_signal_date", "previous_delay_minutes", "previous_window_seconds",
            "execution_delay_minutes", "execution_window_seconds"}
        if (not isinstance(record, dict) or set(record) != expected
                or (record["execution_delay_minutes"], record["execution_window_seconds"]) != (25, 1500)
                or any(type(record[k]) is not int for k in expected - {"after_signal_date"})
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(record["after_signal_date"]))
                or (self.execution_delay_minutes, self.execution_window_seconds) !=
                    (record["previous_delay_minutes"], record["previous_window_seconds"])):
            raise ValueError("DEFERRED_ORDINARY_CLOCK_CHANGED")
        signal, _, _ = self._metadata(data, clock)
        if (signal <= record["after_signal_date"] or not maintenance_projection and (
                data.get("data_gaps") or data.get("source_date") != signal
                or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"})):
            return
        if any(engine._pending() for engine in self._active_engines().values()):
            raise ValueError("DEFERRED_ORDINARY_CLOCK_REQUIRES_RECONCILED_ACCOUNT")
        if not any(json.loads(row[0]) == record for row in self.db.execute(
                "SELECT detail FROM events WHERE event='ORDINARY_EXECUTION_CLOCK_DEFERRED'")):
            raise ValueError("DEFERRED_ORDINARY_CLOCK_AUDIT_CHANGED")
        return deepcopy(record)

    def _activate_next_ordinary_clock(self, record, data, clock):
        """Stage a validated successor clock for the caller's accepted-plan commit."""
        if record is None:
            return None
        if self.meta.get("next_ordinary_execution_clock") != record:
            raise ValueError("DEFERRED_ORDINARY_CLOCK_CHANGED")
        self.execution_delay_minutes, self.execution_window_seconds = 25, 1500
        scheduled = self._scheduled_open(data["next_open_utc"]).isoformat()
        self.meta.update(execution_delay_minutes=25, execution_window_seconds=1500,
            execution_time_utc=scheduled, next_expected_execution_utc=scheduled,
            next_ordinary_execution_clock=None)
        return ("ORDINARY_EXECUTION_CLOCK_APPLIED", {**record, "signal_date": data["signal_date"]}, clock)

    def _manual_schedule_bound(self, frozen, *, engine=None):
        """An existing per-signal grant retains its original sealed clock."""
        signal, execution = frozen.get("signal_date"), frozen.get("execution_date")
        if not signal:
            return False
        keys = ("paper_first_execution", "paper_first_continuation",
                "paper_same_day_catchup", "paper_same_day_catchup_renewal")
        def matches(record):
            return record is not None and (not isinstance(record, dict)
                or record.get("signal_date") == signal
                or execution is not None and record.get("execution_date") == execution)
        if any(matches(self.meta.get(key)) for key in keys):
            return True
        reset = self.meta.get("paper_reset") or {}
        if reset.get("request", {}).get("signal_date") == signal:
            return True
        slots = tuple(key + ":" + signal for key in keys[:2])
        if any(self.db.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone() for key in slots):
            return True
        engines = (engine,) if engine is not None else self._active_engines().values()
        return any(any(matches(item._get(key, None)) for key in keys)
            or any(item.db.execute("SELECT 1 FROM settings WHERE key=?", (key,)).fetchone() for key in slots)
            for item in engines)

    def _rebind_unexecuted_schedule(self, sid, frozen, clock, *, explicit_update):
        """Rebind only a future, untouched ordinary cached signal; never infer."""
        target = (self.execution_delay_minutes, self.execution_window_seconds)
        if target != (25, 1500) and self.execution_delay_minutes != 30:
            return
        opening = timestamp(frozen["next_open_utc"])
        scheduled = self._scheduled_open(frozen["next_open_utc"])
        prior = (frozen.get("execution_delay_minutes"), frozen.get("execution_window_seconds"))
        if (timestamp(frozen.get("execution_time_utc", frozen["next_open_utc"])) == scheduled
                and prior == target):
            return
        broker = self.best_broker
        allowed_prior = ((0, 600), (30, 600)) if target == (25, 1500) else ((0, 600),)
        if (not explicit_update or not self.stop_event.is_set()
                or self.worker and self.worker.is_alive()
                or broker is not None and (not broker.stop_event.is_set()
                    or broker.worker and broker.worker.is_alive())
                or clock >= opening or type(prior[0]) is not int or prior not in allowed_prior
                or timestamp(frozen.get("execution_time_utc", frozen["next_open_utc"])) != opening + timedelta(minutes=prior[0])
                or target != (25, 1500) and self.execution_window_seconds != 600
                or not self.allow_partial_quotes or frozen.get("allow_partial_quotes") is not True):
            raise ValueError("PAPER_EXECUTION_SCHEDULE_REQUIRES_FUTURE_PAUSED_ORDINARY_SIGNAL")
        engine = self.engines[sid]
        if self._manual_schedule_bound(frozen, engine=engine):
            raise ValueError("PAPER_EXECUTION_SCHEDULE_MANUAL_BINDING_PRESERVED")
        engine._paper_first_no_attempt(frozen)
        rebound = {**frozen, "execution_time_utc": scheduled.isoformat(),
                   "execution_delay_minutes": target[0], "execution_window_seconds": target[1]}
        metadata = self.meta["book_plan_metadata"]
        metadata[sid] = rebound
        detail = dict(strategy_id=sid, signal_date=frozen["signal_date"], execution_date=frozen["execution_date"],
            previous_execution_time_utc=frozen.get("execution_time_utc", frozen["next_open_utc"]),
            execution_time_utc=scheduled.isoformat(), previous_delay_minutes=prior[0],
            execution_delay_minutes=target[0], execution_window_seconds=target[1], orders_created=0)
        try:
            self._persist(event=("PAPER_EXECUTION_SCHEDULE_CHANGED", detail, clock))
        except Exception:
            metadata[sid] = frozen
            raise

    def _complete_duration_source_proof(self, sid, frozen, data, clock):
        """Explicit pre-open repair of omitted witnesses; sealed targets stay immutable."""
        missing = {"model_receipt/duration_tree_2025", "model_contract/R6", "model_closure/R6"}
        old, current = frozen.get("source_refs"), data.get("source_refs")
        if (sid != "R6_DURATION_TREE" or not isinstance(old, dict) or not isinstance(current, dict)
                or set(current) - set(old) != missing or set(old) - set(current)
                or any(current[key] != value for key, value in old.items())):
            return frozen  # The original comparison remains authoritative for every other mismatch.
        engine, broker = self.engines[sid], self.best_broker
        started = time.monotonic()
        with ExitStack() as locks:
            if broker is not None:
                locks.enter_context(broker.lock)
                locks.enter_context(broker.engine.lock)
            locks.enter_context(engine.lock)
            plan = self.plans[sid]
            model = old.get("model/duration_tree_2025")
            if (not self.manual_data_updates or not self.stop_event.is_set()
                    or self.worker and self.worker.is_alive() or self.closed or self.halt_event.is_set()
                    or not engine.paper_only or engine.mode != "paper" or engine.broker is not None
                    or engine.account_id != "paper-" + sid
                    or engine._get("paper_account_identity", None) != engine.account_id
                    or engine.halt_event.is_set() or engine._pending()
                    or self._manual_schedule_bound(frozen, engine=engine)
                    or plan.get("source_refs") != old or plan.get("strategy_id") != sid
                    or plan.get("signal_date") != frozen.get("signal_date")
                    or plan.get("execution_date") != frozen.get("execution_date")
                    or plan.get("model_refs") != {"duration_tree_2025": model}
                    or not isinstance(model, dict)
                    or plan.get("source_hashes") != {"duration_tree_2025": model.get("sha256")}
                    or frozen.get("execution_delay_minutes") != self.execution_delay_minutes
                    or frozen.get("execution_window_seconds") != self.execution_window_seconds
                    or timestamp(frozen["execution_time_utc"]) != self._scheduled_open(frozen["next_open_utc"])):
                raise ValueError("DURATION_SOURCE_PROOF_REQUIRES_UNTOUCHED_PAUSED_PLAN")
            engine._require_stopped()
            if broker is not None:
                broker._require_manual_preparation()
            engine._paper_first_no_attempt(frozen)
            if not timestamp(frozen["signal_close_utc"]) <= clock < timestamp(frozen["next_open_utc"]):
                raise ValueError("DURATION_SOURCE_PROOF_PREOPEN_ONLY")
            before = _fingerprint((plan, self.close_states.get(sid), engine.paper_book(), frozen))
            # Recheck the original source owner, including model/receipt/contract/closure bytes.
            checked = self._book_source_data(sid, self.source.status(now=clock))
            finished = clock + timedelta(seconds=time.monotonic() - started)
            self._metadata(checked, finished)
            if (checked.get("source_refs") != current or checked.get("data_gaps")
                    or checked.get("status") != "READY" or checked.get("source_date") != frozen["signal_date"]
                    or any(checked.get(key) != frozen.get(key) for key in
                        ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                    or not finished < timestamp(frozen["next_open_utc"])
                    or before != _fingerprint((self.plans[sid], self.close_states.get(sid), engine.paper_book(), frozen))):
                raise ValueError("DURATION_SOURCE_PROOF_CHANGED_DURING_RECHECK")
            engine._require_stopped()
            if (not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                    or self.closed or self.halt_event.is_set() or engine.halt_event.is_set()
                    or engine._pending() or self._manual_schedule_bound(frozen, engine=engine)):
                raise ValueError("DURATION_SOURCE_PROOF_REQUIRES_UNTOUCHED_PAUSED_PLAN")
            if broker is not None:
                broker._require_manual_preparation()
            engine._paper_first_no_attempt(frozen)
            rebound = {**frozen, "source_refs": deepcopy(current)}
            self.meta["book_plan_metadata"][sid] = rebound
            try:
                self._persist(event=("DURATION_SOURCE_PROOF_COMPLETED", dict(strategy_id=sid,
                    signal_date=frozen["signal_date"], execution_date=frozen["execution_date"],
                    added_source_refs={key: current[key] for key in sorted(missing)},
                    previous_source_sha256=_fingerprint(old), source_sha256=_fingerprint(current),
                    sealed_plan_sha256=_fingerprint(plan), orders_created=0), finished))
            except BaseException:
                self.meta["book_plan_metadata"][sid] = frozen
                raise
            return rebound

    def _prepare_active_members(self, data, clock, *, explicit_update=False):
        """Prepare independently ready books using the same serialized source owner."""
        next_clock = self._next_ordinary_clock(data, clock, explicit_update=explicit_update)
        signal, execution, _ = self._metadata(data, clock)
        inputs = self._books_input()
        needed, errors = {}, {}
        metadata_by_book = self.meta.setdefault("book_plan_metadata", {})
        for sid in self._active_ids():
            if self._executed(sid, execution):
                continue  # A later display update cannot rewrite an already completed frozen signal.
            prior = self.plans.get(sid)
            frozen = metadata_by_book.get(sid, {})
            if prior and frozen.get("signal_date") == signal:
                try:
                    if any(frozen.get(k) != data.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
                        raise ValueError("FROZEN_BOOK_CLOCK_CHANGED")
                    checked_source = self._book_source_data(sid, data)
                    if explicit_update:
                        frozen = self._complete_duration_source_proof(sid, frozen, checked_source, clock)
                    self._match_source_refs(frozen.get("source_refs"), checked_source, "FROZEN_BOOK_SOURCE_CHANGED")
                    self._rebind_unexecuted_schedule(sid, frozen, clock, explicit_update=explicit_update)
                    continue
                except Exception as exc:
                    errors[sid] = str(exc)
                    continue
            if self._processed(sid, execution):
                errors[sid] = "PARTIAL_BOOK_REQUIRES_ORIGINAL_FROZEN_PLAN"
            else:
                needed[sid] = inputs[sid]
        states = {}
        manual_waiting = set(needed) if self.manual_data_updates and not explicit_update else set()
        if manual_waiting:
            for sid in manual_waiting:
                self.book_status[sid] = dict(status="WAITING_MANUAL_UPDATE", signal_date=signal,
                    execution_date=execution, reason="等待每日手动更新并准备本策略目标；保留历史计划和实际成交")
            needed = {}
        if needed:
            try:
                states = self.source.close_states(books=needed, signal_date=signal)
            except Exception:
                # One missing mark must not block another independent account.
                for sid, book in needed.items():
                    try:
                        states.update(self.source.close_states(books={sid: book}, signal_date=signal))
                    except Exception as exc:
                        errors[sid] = str(exc)
            for sid in tuple(states):
                try:
                    value = states[sid]
                    if sid not in needed or value.get("signal_date") != signal or value.get("valuation_basis") != "SIGNAL_CLOSE":
                        raise ValueError("SIGNAL_CLOSE_STATE_CLOCK")
                    if abs(sum(number(w, "收盘权重") for w in value["weights"].values()) + number(value["cash_weight"], "收盘现金权重") - 1) > 1e-8:
                        raise ValueError("SIGNAL_CLOSE_STATE_WEIGHTS")
                    value["units"] = {code.removeprefix("US."): qty for code, qty in inputs[sid]["positions"].items()}
                    if sid == "R7_GROSS_LINEAR":
                        value["previous_requested_gross"] = self._requested_input(sid, signal)
                    if "equity" in value:
                        self.engines[sid].paper_record_close(signal, value)
                except Exception as exc:
                    errors[sid] = str(exc)
                    del states[sid]
            for sid in needed.keys() - states.keys():
                errors.setdefault(sid, "SIGNAL_CLOSE_STATE_UNAVAILABLE")
        if states:
            previous = None
            try:
                with _manual_inference_update(self, self.source) if explicit_update else nullcontext():
                    loaded = self.source.load(states=states, now=clock)
                self._metadata(loaded, clock)
                if any(loaded.get(k) != data.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
                    raise ValueError("SOURCE_CHANGED_DURING_PLAN")
                plans = loaded.get("plans", {})
                if set(plans) - set(states):
                    raise ValueError("UNREQUESTED_BOOK_PLAN")
                prepared = {}
                for sid in states:
                    plan = plans.get(sid)
                    if not plan:
                        errors[sid] = loaded.get("strategy_status", {}).get(sid, {}).get("reason", "FROZEN_PLAN_UNAVAILABLE")
                        continue
                    try:
                        if plan.get("strategy_id", sid) != sid or plan.get("signal_date", signal) != signal:
                            raise ValueError("FROZEN_PLAN_IDENTITY_CHANGED")
                        weights = [number(row.get("target_weight"), "目标权重") for row in plan.get("rows", [])]
                        if any(weight > 1 for weight in weights) or abs(sum(weights) + number(plan.get("target_cash_weight"), "目标现金权重") - 1) > 1e-8:
                            raise ValueError("PLAN_WEIGHTS_NOT_NORMALIZED")
                        holds = exact_hold_units(plan)
                        if any(inputs[sid]["positions"].get(code, 0) != qty for code, qty in holds.items()):
                            raise ValueError("EXACT_HOLD_UNITS_CHANGED")
                        after = (accepted_requested_gross_state(plan, states[sid], signal)
                            if sid == "R7_GROSS_LINEAR" else None)
                    except Exception as exc:
                        errors[sid] = str(exc)
                        continue
                    prepared[sid] = (deepcopy(plan), deepcopy(states[sid]), deepcopy(after))
                if next_clock and (errors or set(prepared) != set(needed)
                        or set(needed) != set(self._active_ids())
                        or self._next_ordinary_clock(loaded, clock, explicit_update=explicit_update) != next_clock):
                    raise ValueError("DEFERRED_ORDINARY_CLOCK_REQUIRES_ALL_ACCEPTED_PLANS")
                if next_clock:
                    previous = (deepcopy(self.meta), deepcopy(self.plans), deepcopy(self.close_states),
                        deepcopy(self.plan_metadata), deepcopy(self.book_status), self.loaded_key,
                        self.execution_delay_minutes, self.execution_window_seconds)
                event = self._activate_next_ordinary_clock(next_clock, loaded, clock) if prepared else None
                for sid, (plan, state, after) in prepared.items():
                    frozen = {k: loaded.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "source_date")}
                    frozen["source_refs"] = deepcopy(plan.get("source_refs", loaded.get("source_refs", {})))
                    frozen.update(execution_time_utc=self._scheduled_open(data["next_open_utc"]).isoformat(),
                        execution_delay_minutes=self.execution_delay_minutes,
                        execution_window_seconds=self.execution_window_seconds, allow_partial_quotes=self.allow_partial_quotes)
                    self.plans[sid], self.close_states[sid], metadata_by_book[sid] = plan, state, frozen
                    if after is not None:
                        self.meta.setdefault("strategy_requested_state", {})[sid] = after
                    self.book_status[sid] = dict(status="WAITING_OPEN", signal_date=signal, execution_date=execution)
                if prepared:
                    self.plan_metadata = {k: loaded.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "source_refs", "source_date")}
                    self.plan_metadata.update(execution_time_utc=self._scheduled_open(data["next_open_utc"]).isoformat(),
                        execution_delay_minutes=self.execution_delay_minutes,
                        execution_window_seconds=self.execution_window_seconds, allow_partial_quotes=self.allow_partial_quotes)
                    self.meta.update(plan_signal_date=signal, plan_execution_date=execution)
                self._persist(event=event)  # The accepted plans and optional clock audit share one commit.
            except Exception as exc:
                if previous is not None:
                    (self.meta, self.plans, self.close_states, self.plan_metadata, self.book_status, self.loaded_key,
                        self.execution_delay_minutes, self.execution_window_seconds) = previous
                for sid in states:
                    errors.setdefault(sid, str(exc))
        for sid, reason in errors.items():
            previous = self.book_status.get(sid, {})
            self.book_status[sid] = dict(previous if previous.get("execution_date") == execution else {},
                status="BLOCKED", signal_date=signal, execution_date=execution, reason=reason, failure_stage="PREPARE")
        return {**errors, **{sid: "MANUAL_PUBLISHED_PLAN_PREPARATION_REQUIRED" for sid in manual_waiting}}

    def _book_execution_window(self, sid, data, clock, *, maintenance_clock=None):
        """One owner for each active book's ordinary or standing deadline."""
        policy = self.engines[sid]._automatic_completion_policy(clock, sid, execution_date=data["execution_date"])
        delay, window = self.execution_delay_minutes, self.execution_window_seconds
        end = self._scheduled_open(data["next_open_utc"]) + timedelta(seconds=window)
        # Only maintenance supplies the original audited successor record.
        # Schema1 standing permissions retain their original clock/close bound.
        if maintenance_clock is not None and (policy is None or policy.get("schema_version", 1) == 2):
            delay, window = maintenance_clock["execution_delay_minutes"], maintenance_clock["execution_window_seconds"]
            end = timestamp(data["next_open_utc"]) + timedelta(minutes=delay, seconds=window)
        if policy is not None:
            if ((not automatic_completion_clock_matches(policy, delay, window)
                    if policy.get("schema_version", 1) == 2 else
                        delay not in (0, 30) or window != policy["priority_window_seconds"])
                    or not self.allow_partial_quotes):
                raise ValueError("AUTOMATIC_COMPLETION_BOOK_POLICY_CHANGED")
            if policy.get("schema_version", 1) != 2:
                end = timestamp(data["next_close_utc"]) - timedelta(seconds=policy["close_buffer_seconds"])
        return policy, end

    def _tick_active_members(self, data, clock, *, supplied_now):
        signal, execution, opening_actual = self._metadata(data, clock)
        opening = self._scheduled_open(data["next_open_utc"])
        self.meta.update({k: data.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "next_close_utc", "source_refs", "data_gaps")})
        self.meta.update(execution_time_utc=opening.isoformat(), sourcecutoff=signal)
        if (not data.get("data_gaps") and data.get("status") in {"READY","OPEN_WINDOW","MISSED_OPEN"}
                and data.get("source_date")==signal):
            clocks = {key:data[key] for key in ("next_refresh_utc","refresh_not_before_utc") if key in data}
            for value in clocks.values():
                if value is not None:
                    timestamp(value)  # Validate the existing source clock before any display update.
            self.meta.update(clocks)
        if self.stop_event.is_set() or self.halt_event.is_set():
            return self.state()
        if data.get("data_gaps") or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}:
            self.meta.update(status="WAITING_SOURCE", reason=data.get("reason", "等待基础日更信号"))
            return self.state()
        errors = self._prepare_active_members(data, clock)
        opening = self._scheduled_open(data["next_open_utc"])
        self._prewarm(data, clock, opening)
        for sid, engine in self._active_engines().items():
            if self.stop_event.is_set() or self.halt_event.is_set():
                break
            if sid in errors or self._executed(sid, execution):
                continue
            frozen = self.meta.get("book_plan_metadata", {}).get(sid, {})
            if frozen.get("signal_date") != signal or sid not in self.plans:
                continue
            try:
                policy, end = self._book_execution_window(sid, data, clock)
            except ValueError as exc:
                errors[sid] = str(exc)
                continue
            if clock < opening:
                self.book_status[sid] = dict(status="WAITING_OPEN", signal_date=signal, execution_date=execution)
                continue
            if clock >= end:
                previous = self.book_status.get(sid, {})
                self.book_status[sid] = dict(previous, status="PARTIALLY_EXECUTED" if self._processed(sid, execution) else "MISSED_OPEN",
                    signal_date=signal, execution_date=execution, reason="本账户窗口已结束；保留实际成交与未完成目标")
                continue
            try:
                book = engine.paper_book()
                codes = {r["code"] for r in self.plans[sid]["rows"] if r["target_weight"]}
                codes.update(r["code"] for r in book["positions"] if r["qty"])
                response = self.quote_feed.quotes_partial(sorted(codes)) if self.allow_partial_quotes else {"quotes": self.quote_feed.quotes(sorted(codes)), "errors": {}}
                fill_clock = clock if supplied_now else _now()
                if not self.allow_partial_quotes:
                    self._fresh_quotes(response["quotes"], fill_clock)
                options = dict(execution_window_seconds=self.execution_window_seconds)
                if policy is not None:
                    options.update(automatic_completion_policy=policy, next_close_utc=data["next_close_utc"])
                if self.allow_partial_quotes:
                    options.update(allow_partial_quotes=True, quote_errors=response["errors"])
                self.book_status[sid] = engine.paper_rebalance(sid, self.plans[sid], response["quotes"],
                    now=fill_clock, next_open_utc=frozen["execution_time_utc"], signal_date=signal,
                    execution_date=execution, signal_close_utc=frozen["signal_close_utc"],
                    source_refs=frozen["source_refs"], fee_bps=FEE_BPS, **options)
                self._persist()
                held = {row["code"] for row in engine.paper_book()["positions"] if row["qty"]}
                if held.issubset(response["quotes"]):
                    try:
                        self._mark(sid, response["quotes"], fill_clock)
                    except Exception as exc:
                        self.meta.setdefault("book_quote_errors", {})[sid] = str(exc)
                if self.book_status[sid].get("skipped"):
                    errors[sid] = self.book_status[sid].get("reason", "等待合格报价")
            except Exception as exc:
                errors[sid] = str(exc)
                previous = self.book_status.get(sid, {})
                self.book_status[sid] = dict(previous, status="BLOCKED", signal_date=signal,
                    execution_date=execution, reason=str(exc), failure_stage="EXECUTE")
        completed = [sid for sid in self._active_ids() if self._executed(sid, execution)]
        pending = [sid for sid in self._active_ids() if sid not in completed]
        self.meta.update(status="EXECUTED" if not pending else "WAITING_OPEN" if clock < opening else "PARTIALLY_EXECUTED" if completed else "BLOCKED",
            last_error="; ".join(f"{sid}: {reason}" for sid, reason in errors.items()),
            reason="已完成账户：" + (", ".join(completed) or "无") + "；各账户按自己的资格与窗口处理")
        if pending and all(self.book_status.get(sid, {}).get("status") == "WAITING_MANUAL_UPDATE" for sid in pending):
            self.meta.update(status="WAITING_MANUAL_UPDATE", reason="等待每日手动更新并准备当期目标；保留现仓和历史成交")
        elif pending and not completed and not errors and all(
                self.book_status.get(sid, {}).get("status") == "MISSED_OPEN" for sid in pending):
            self.meta.update(status="MISSED_OPEN", reason="本期各账户执行窗口已结束；保留持仓和未完成目标，等待下一完成日")
        if (not self.manual_data_updates and clock >= opening + timedelta(seconds=self.execution_window_seconds)
                and opening_actual <= clock < timestamp(data["next_close_utc"])):
            self._mark_current_books(now=clock if supplied_now else None,
                record_cash=True, respect_stop=True, active_only=True)
        self._persist()
        return self.state()

    @staticmethod
    def _file_sha(path):
        value = hashlib.sha256()
        with Path(path).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                value.update(block)
        return value.hexdigest()

    def _reset_owned_path(self, path):
        daily = Path(self.source.daily_root).resolve()
        lexical_root = self.path.absolute()
        for candidate in (Path(path).absolute(), *Path(path).absolute().parents):
            if candidate == lexical_root:
                break
            if candidate.is_symlink() or (hasattr(candidate, "is_junction") and candidate.is_junction()):
                raise ValueError("HGB_RESET_PATH_LINK_FORBIDDEN")
        root, resolved = self.path.resolve(), Path(path).resolve()
        if (root == daily or not root.is_relative_to(daily) or resolved == root
                or not resolved.is_relative_to(root)):
            raise ValueError("HGB_RESET_PATH_OUTSIDE_OWNED_DAILY_ROOT")
        return resolved

    def _reset_archive(self, record):
        request = record["request"]
        loaded = record["loaded"]
        bound = loaded["archive"]
        daily = Path(self.source.daily_root).resolve()
        runtime = Path(self.source.runtime_root).resolve()
        path = Path(bound["path"]).resolve()
        if (runtime == daily or not runtime.is_relative_to(daily) or not path.is_relative_to(runtime)
                or path.name != "plans.json" or path.parent.name != request["signal_date"]
                or path.parent.parent.name != request["reset_id"]):
            raise ValueError("HGB_RESET_SOURCE_ARCHIVE_PATH_INVALID")
        if self._file_sha(path) != bound["sha256"]:
            raise ValueError("HGB_RESET_SOURCE_ARCHIVE_CHANGED")
        archived = json.loads(path.read_text(encoding="utf-8"))
        if any(archived.get(key) != loaded.get(key) for key in
               ("plans", "source_refs", "reset_request", "reset_request_sha256", "assumed_states")):
            raise ValueError("HGB_RESET_SOURCE_ARCHIVE_BINDING_INVALID")

    def _reset_book_proof(self, path):
        path = self._reset_owned_path(path)
        files = {}
        for child in sorted(path.rglob("*")):
            self._reset_owned_path(child)
            if child.is_symlink() or (hasattr(child, "is_junction") and child.is_junction()):
                raise ValueError("HGB_RESET_BOOK_LINK_FORBIDDEN")
            if child.is_file():
                files[str(child.relative_to(path))] = self._file_sha(child)
        database = path / "state.sqlite3"
        digest, counts = hashlib.sha256(), {}
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as connection:
            if connection.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                raise ValueError("HGB_RESET_SQLITE_INTEGRITY_FAILED")
            names = [row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                count = 0
                for row in connection.execute("SELECT * FROM " + quoted + " ORDER BY rowid"):
                    digest.update(_bytes([name, list(row)]))
                    count += 1
                counts[name] = count
        return {"files": files, "sqlite_sha256": digest.hexdigest(), "table_counts": counts, "quick_check": "ok"}

    def _archive_reset_books(self, record):
        self._reset_archive(record)
        if (_fingerprint(record["request"]) != record["request_sha256"]
                or set(record["request"]["strategy_ids"]) != set(HGB_STRATEGIES)):
            raise ValueError("HGB_RESET_TRANSACTION_BINDING_INVALID")
        for sid in HGB_STRATEGIES:
            source = self._reset_owned_path(self.path / "books" / sid)
            destination = self._reset_owned_path(self.path / "archives" / "hgb_resets" / record["request"]["reset_id"] / sid)
            if record["archives"].get(sid) != str(destination):
                raise ValueError("HGB_RESET_ARCHIVE_LOCATION_CHANGED")
            if destination.exists():
                if sid not in record["old_book_proofs"] or self._reset_book_proof(destination) != record["old_book_proofs"][sid]:
                    raise ValueError("HGB_RESET_OLD_ARCHIVE_CHANGED")
                continue
            engine = self.engines.pop(sid, None)
            if engine is not None:
                engine.close()
            if not (source / "state.sqlite3").is_file():
                raise ValueError("HGB_RESET_ORIGINAL_BOOK_MISSING")
            # Checkpoint through SQLite before any move; a crash may have retained a WAL.
            with closing(sqlite3.connect(source / "state.sqlite3")) as connection:
                if connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
                    raise ValueError("HGB_RESET_BOOK_WAL_BUSY")
            proof = self._reset_book_proof(source)
            prior = record["old_book_proofs"].get(sid)
            if prior is not None and prior != proof:
                raise ValueError("HGB_RESET_ORIGINAL_BOOK_CHANGED")
            record["old_book_proofs"][sid] = proof
            record["phase"] = "ARCHIVING_" + sid
            self.meta["paper_reset"] = record
            self._persist()
            destination.parent.mkdir(parents=True, exist_ok=True)
            if destination.exists():
                raise ValueError("HGB_RESET_ARCHIVE_ALREADY_EXISTS")
            source.rename(destination)
            if self._reset_book_proof(destination) != proof:
                raise ValueError("HGB_RESET_ARCHIVE_COPY_MISMATCH")
        record["phase"] = "ARCHIVED"
        self._persist()

    def _finish_hgb_reset(self, record):
        self._reset_archive(record)
        request, loaded = record["request"], record["loaded"]
        for sid in HGB_STRATEGIES:
            engine = self.engines.get(sid)
            if engine is None:
                engine = Engine(self.path / "books" / sid, quote_provider=self.quote_feed.quotes,
                                paper_account_id="paper-" + sid, paper_only=True)
                self.engines[sid] = engine
            if engine._get("paper_epoch_id", None) not in (None, request["reset_id"]):
                raise ValueError("HGB_RESET_NEW_EPOCH_IDENTITY_CHANGED")
            book = engine.paper_book()
            if (book["cash"] != 10000 or book["positions"] or book["fees"] != 0 or book["trade_count"]
                    or engine.db.execute("SELECT COUNT(*) FROM paper_batches").fetchone()[0]
                    or engine.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]):
                raise ValueError("HGB_RESET_NEW_BOOK_MUST_BE_FRESH")
            engine._set("paper_epoch_id", request["reset_id"])
            engine.cancel_step.set()
            self.book_status.pop(sid, None)
            self.close_states[sid] = {**deepcopy(loaded["assumed_states"][sid]), "cash": 10000.0,
                                      "equity": 10000.0, "reset_id": request["reset_id"]}
        self.meta.setdefault("inactive_plan_metadata", {}).setdefault("RAW_A2", deepcopy(self.plan_metadata))
        self.plans.update(deepcopy(loaded["plans"]))
        self.plan_metadata = {key: deepcopy(loaded.get(key)) for key in ("signal_date", "execution_date", "next_open_utc",
            "signal_close_utc", "source_refs", "source_date")}
        self.plan_metadata.update(reset_id=request["reset_id"], reset_request_sha256=record["request_sha256"],
            execution_time_utc=loaded["next_open_utc"], execution_delay_minutes=0, execution_window_seconds=600,
            allow_partial_quotes=self.allow_partial_quotes if hasattr(self, "allow_partial_quotes") else self.meta.get("allow_partial_quotes", False))
        self.execution_delay_minutes, self.execution_window_seconds = 0, 600
        self.meta.update(active_strategy_ids=list(HGB_STRATEGIES), running=False, status="STOPPED",
            execution_delay_minutes=0, execution_window_seconds=600, reset_id=request["reset_id"],
            plan_signal_date=loaded["signal_date"], plan_execution_date=loaded["execution_date"], sourcecutoff=loaded["signal_date"],
            signal_date=loaded["signal_date"], execution_date=loaded["execution_date"], source_refs=deepcopy(loaded["source_refs"]),
            next_open_utc=loaded["next_open_utc"], signal_close_utc=loaded["signal_close_utc"], next_close_utc=loaded["next_close_utc"],
            execution_time_utc=loaded["next_open_utc"], next_expected_execution_utc=loaded["next_open_utc"],
            data_gaps=[], last_error="", connection_error="", book_quote_errors={}, book_quote_asof={},
            reason="两套HGB已按用户请求以新现金epoch重启；Raw A2暂停，旧记录已归档")
        self.meta.pop("paper_same_day_catchup", None)
        self.loaded_key = None
        self._prewarm_key = None
        previous_phase = record["phase"]
        record["phase"] = "COMMITTED"
        try:
            self._persist()
        except Exception:
            record["phase"] = previous_phase
            self.meta.update(status="BLOCKED", running=False, reason="HGB重启事务尚未提交；执行保持暂停")
            raise

    def reset_hgb(self, reset_request, now=None):
        """Archive two original paper journals and establish an explicitly requested cash epoch."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("HGB_RESET_WAIT_FOR_TICK")
        try:
            with self.lock:
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set()):
                    raise ValueError("HGB_RESET_REQUIRES_STOPPED_UNLOCKED_WORKER")
                clock = _now(now)
                request = _reset_request(reset_request, now=clock)
                if set(request["strategy_ids"]) != set(HGB_STRATEGIES):
                    raise ValueError("HGB_RESET_REQUIRES_BOTH_HGB_BOOKS")
                previous = self.meta.get("paper_reset")
                if previous and previous["request"]["reset_id"] == request["reset_id"]:
                    if previous["request"] != request:
                        raise ValueError("HGB_RESET_REQUEST_CHANGED")
                    if previous["phase"] != "COMMITTED":
                        self._archive_reset_books(previous)
                        self._finish_hgb_reset(previous)
                    return self.state()
                if previous and previous.get("phase") != "COMMITTED":
                    raise ValueError("HGB_RESET_UNFINISHED_TRANSACTION")
                for sid in HGB_STRATEGIES:
                    engine = self.engines[sid]
                    engine._require_stopped()
                    if not engine.paper_only or engine.mode != "paper" or engine.broker is not None or engine.halt_event.is_set():
                        raise ValueError("HGB_RESET_PAPER_IDENTITY_REQUIRED")
                    if engine.path.resolve() != self._reset_owned_path(self.path / "books" / sid):
                        raise ValueError("HGB_RESET_BOOK_LOCATION_CHANGED")
                loaded = self.source.load(None, now=clock, reset_request=request)
                signal, execution, opening = self._metadata(loaded, clock)
                if (signal != request["signal_date"] or loaded.get("source_date") != signal or not clock < opening
                        or loaded.get("status") not in {"READY", "OPEN_WINDOW"} or loaded.get("data_gaps")
                        or set(loaded.get("plans", {})) != set(HGB_STRATEGIES)
                        or loaded.get("reset_request") != request
                        or loaded.get("reset_request_sha256") != _fingerprint(request)
                        or loaded.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != request["expected_package_sha256"]):
                    raise ValueError("HGB_RESET_DIRECT_CURRENT_SOURCE_REQUIRED")
                for sid, plan in loaded["plans"].items():
                    if (plan.get("policy_id") != "HGB_TOP20_RISK_R1" or plan.get("source_date") != signal
                            or plan.get("reset_id") != request["reset_id"]
                            or plan.get("account_basis") != "USER_REQUESTED_POST_LIQUIDATION_CASH_START"
                            or plan.get("valuation_basis") != "POST_LIQUIDATION_ASSUMPTION"
                            or plan.get("target_origin_account_basis") != "CASH_START"
                            or plan.get("execution_condition") != "ACCOUNT_FLAT_AFTER_CONFIRMED_LIQUIDATION"
                            or loaded.get("assumed_states", {}).get(sid) != {"weights": {}, "cash_weight": 1.0,
                                "valuation_basis": "POST_LIQUIDATION_ASSUMPTION"}):
                        raise ValueError("HGB_RESET_ASSUMED_CASH_PLAN_REQUIRED")
                    codes = [row["code"] for row in plan["rows"]]
                    if (len(set(codes)) != len(codes) or any(not code_valid(code) for code in codes)
                            or any(number(row["weight_before"], "原权重") != 0 for row in plan["rows"])
                            or any(number(row["target_weight"], "目标权重") > .10 + 1e-9 for row in plan["rows"])
                            or abs(sum(number(row["target_weight"], "目标权重") for row in plan["rows"])
                                   + number(plan["target_cash_weight"], "现金权重") - 1) > 1e-8):
                        raise ValueError("HGB_RESET_PLAN_WEIGHTS_INVALID")
                current = self.source.status(now=clock)
                if (current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or current.get("data_gaps")
                        or any(current.get(key) != loaded.get(key) for key in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
                    raise ValueError("HGB_RESET_SOURCE_CHANGED_DURING_FREEZE")
                self._match_source_refs(loaded["source_refs"], current, "HGB_RESET_SOURCE_CHANGED_DURING_FREEZE")
                record = {"request": request, "request_sha256": _fingerprint(request), "loaded": deepcopy(loaded),
                    "phase": "PREPARED", "old_book_proofs": {},
                    "prior_cohort": {"plans": {sid: deepcopy(self.plans.get(sid)) for sid in HGB_STRATEGIES},
                        "book_status": {sid: deepcopy(self.book_status.get(sid)) for sid in HGB_STRATEGIES},
                        "close_states": {sid: deepcopy(self.close_states.get(sid)) for sid in HGB_STRATEGIES},
                        "plan_metadata": deepcopy(self.plan_metadata)}, "archives": {sid: str(self._reset_owned_path(
                        self.path / "archives" / "hgb_resets" / request["reset_id"] / sid)) for sid in HGB_STRATEGIES}}
                self._reset_archive(record)
                self.meta["paper_reset"] = record
                self._persist()
                self._archive_reset_books(record)
                self._finish_hgb_reset(record)
                self._event("HGB_PAPER_EPOCH_RESET_COMMITTED", {"reset_id": request["reset_id"], "signal_date": signal,
                    "execution_date": execution, "initial_cash_per_strategy": 10000.0, "archives": record["archives"]}, clock)
                return self.state()
        finally:
            self.tick_lock.release()

    def _initial_hgb_target_plans(self, reset):
        """Validate the original epoch archive and only its currently active revision."""
        self._reset_archive(reset)
        revision = self.meta.get("paper_target_revision")
        if not revision:
            return reset["loaded"]["plans"]
        from .best_broker import BestBroker
        template = revision.get("source_template", {})
        request = BestBroker._source_revision_request(reset["request"], revision.get("package_sha256", ""))
        metadata_for_hash = deepcopy(self.plan_metadata)
        # Bind the frozen source clock before either metadata hash path.
        template_loaded = template.get("loaded", {})
        template_open = template_loaded.get("next_open_utc")
        current_time = metadata_for_hash.get("execution_time_utc")
        if (any(metadata_for_hash.get(key) != template_loaded.get(key) for key in
                ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                or not isinstance(template_open, str) or not isinstance(current_time, str)
                or timestamp(current_time) != timestamp(template_open)):
            raise ValueError("HGB_TARGET_REVISION_AUTHORIZATION_CHANGED")
        # Legacy restarts may use +00:00 while the immutable template uses Z.
        # Hash the original lexeme only for the same instant; other fields stay exact.
        if (revision.get("metadata_sha256") != _fingerprint(metadata_for_hash)
                and isinstance(template_open, str) and isinstance(current_time, str)
                and metadata_for_hash.get("execution_delay_minutes") == 0
                and timestamp(current_time) == timestamp(template_open)):
            metadata_for_hash["execution_time_utc"] = template_open
        if (revision.get("original_epoch_id") != reset["request"]["reset_id"]
                or revision.get("original_request_sha256") != reset["request_sha256"]
                or template.get("request") != request or template.get("request_sha256") != _fingerprint(request)
                or revision.get("plans_sha256") != _fingerprint(revision.get("plans"))
                or revision.get("metadata_sha256") != _fingerprint(metadata_for_hash)
                or revision.get("plans") != {sid: self.plans.get(sid) for sid in HGB_STRATEGIES}
                or self.plan_metadata.get("source_template_id") != request["reset_id"]
                or self.plan_metadata.get("source_template_request_sha256") != _fingerprint(request)
                or self.plan_metadata.get("source_refs") != template.get("loaded", {}).get("source_refs")
                or self.plan_metadata.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != revision.get("package_sha256")):
            raise ValueError("HGB_TARGET_REVISION_AUTHORIZATION_CHANGED")
        self._reset_archive(template)
        return revision["plans"]

    def revise_hgb_targets(self, reset_id, expected_package_sha256, now=None):
        """Update two pending cash-epoch targets without resetting any book or journal."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("HGB_TARGET_REVISION_WAIT_FOR_TICK")
        try:
            with self.lock:
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set()):
                    raise ValueError("HGB_TARGET_REVISION_REQUIRES_STOPPED_UNLOCKED_WORKER")
                clock = _now(now)
                if (not isinstance(reset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_id)
                        or not isinstance(expected_package_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_package_sha256)):
                    raise ValueError("HGB_TARGET_REVISION_IDENTITY_REQUIRED")
                reset = self.meta.get("paper_reset", {})
                if (reset.get("phase") != "COMMITTED" or reset.get("request", {}).get("reset_id") != reset_id
                        or reset.get("request_sha256") != _fingerprint(reset.get("request"))
                        or set(self._active_ids()) != set(HGB_STRATEGIES)
                        or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
                    raise ValueError("HGB_TARGET_REVISION_ORIGINAL_EPOCH_REQUIRED")
                expected = self._initial_hgb_target_plans(reset)
                if any(self.plans.get(sid) != expected[sid] for sid in HGB_STRATEGIES):
                    raise ValueError("HGB_TARGET_REVISION_ORIGINAL_PLAN_CHANGED")
                old_metadata = self.plan_metadata
                signal, execution, opening = self._metadata({**old_metadata, "next_close_utc":self.meta["next_close_utc"]}, clock)
                if (signal != reset["request"]["signal_date"] or execution != reset["loaded"]["execution_date"]
                        or clock >= opening or self.meta.get("paper_same_day_catchup")
                        or clock < timestamp(self.meta.get("paper_target_revision", {}).get("prepared_at", reset["request"]["requested_at"]))):
                    raise ValueError("HGB_TARGET_REVISION_BEFORE_INITIAL_OPEN_REQUIRED")
                for sid in HGB_STRATEGIES:
                    engine = self.engines[sid]
                    engine._require_stopped()
                    book = engine.paper_book()
                    if (not engine.paper_only or engine.mode != "paper" or engine.broker is not None
                            or engine.account_id != engine.paper_account_id or engine.halt_event.is_set() or engine._pending()
                            or engine._get("paper_epoch_id", None) != reset_id
                            or engine.path.resolve() != self._reset_owned_path(self.path / "books" / sid)
                            or book["cash"] != 10000 or book["positions"] or book["trade_count"] or book["fees"] != 0
                            or any(engine.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0]
                                   for table in ("paper_batches", "paper_fills", "orders", "order_fills"))):
                        raise ValueError("HGB_TARGET_REVISION_UNEXECUTED_CASH_BOOK_REQUIRED")
                current = self.source.status(now=clock)
                self._metadata(current, clock)
                if (current.get("status") != "READY" or current.get("ready") is not True or current.get("data_gaps")
                        or any(current.get(key) != old_metadata.get(key) for key in
                               ("signal_date","execution_date","next_open_utc","signal_close_utc"))
                        or current.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                        or any(current.get("source_refs", {}).get(key) != old_metadata.get("source_refs", {}).get(key)
                               for key in ("frozen_calendar","session_hours_rules"))):
                    raise ValueError("HGB_TARGET_REVISION_CURRENT_SOURCE_INVALID")
                if old_metadata.get("source_refs", {}).get("selected/package.json", {}).get("sha256") == expected_package_sha256:
                    self._match_source_refs(old_metadata["source_refs"],current,"HGB_TARGET_REVISION_SOURCE_CHANGED")
                    return self.state()
                from .best_broker import BestBroker
                request = BestBroker._source_revision_request(reset["request"],expected_package_sha256)
                loaded = self.source.load(None,now=clock,reset_request=request)
                self._metadata(loaded,clock)
                if (loaded.get("status") != "READY" or loaded.get("ready") is not True or loaded.get("data_gaps")
                        or loaded.get("model_fit_calls", 0) != 0
                        or set(loaded.get("plans",{})) != set(HGB_STRATEGIES)
                        or loaded.get("reset_request") != request or loaded.get("reset_request_sha256") != _fingerprint(request)
                        or any(loaded.get(key) != current.get(key) for key in
                               ("signal_date","execution_date","next_open_utc","signal_close_utc"))
                        or loaded.get("source_refs",{}).get("selected/package.json",{}).get("sha256") != expected_package_sha256):
                    raise ValueError("HGB_TARGET_REVISION_DIRECT_SOURCE_REQUIRED")
                self._match_source_refs(loaded["source_refs"],current,"HGB_TARGET_REVISION_SOURCE_CHANGED")
                template = dict(request=deepcopy(request),request_sha256=_fingerprint(request),loaded=deepcopy(loaded))
                self._reset_archive(template)
                plans=deepcopy(loaded["plans"])
                for sid,plan in plans.items():
                    if (plan.get("policy_id") != "HGB_TOP20_RISK_R1" or plan.get("source_date") != signal
                            or plan.get("reset_id") != request["reset_id"] or plan.get("model_fit_calls",0) != 0
                            or plan.get("account_basis") != "USER_REQUESTED_POST_LIQUIDATION_CASH_START"
                            or plan.get("valuation_basis") != "POST_LIQUIDATION_ASSUMPTION"
                            or plan.get("target_origin_account_basis") != "CASH_START"
                            or loaded.get("assumed_states",{}).get(sid) != {"weights":{},"cash_weight":1.0,"valuation_basis":"POST_LIQUIDATION_ASSUMPTION"}):
                        raise ValueError("HGB_TARGET_REVISION_CASH_START_REQUIRED")
                    codes=[row["code"] for row in plan["rows"]]
                    if (not codes or len(codes)!=len(set(codes)) or any(not code_valid(code) for code in codes)
                            or any(number(row["weight_before"],"原权重")!=0 for row in plan["rows"])
                            or any(number(row["target_weight"],"目标权重")>.10+1e-9 for row in plan["rows"])
                            or abs(sum(number(row["target_weight"],"目标权重") for row in plan["rows"])+number(plan["target_cash_weight"],"现金权重")-1)>1e-8):
                        raise ValueError("HGB_TARGET_REVISION_WEIGHTS_INVALID")
                    plan.update(reset_id=reset_id,account_basis="USER_REQUESTED_REVISED_PAPER_CASH_START",valuation_basis="PAPER_CASH_EPOCH")
                    plan.pop("execution_condition",None)
                metadata={key:deepcopy(loaded.get(key)) for key in ("signal_date","execution_date","next_open_utc","signal_close_utc","source_refs","source_date")}
                metadata.update(reset_id=reset_id,reset_request_sha256=reset["request_sha256"],execution_time_utc=loaded["next_open_utc"],
                    execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True,
                    source_template_id=request["reset_id"],source_template_request_sha256=_fingerprint(request))
                revision=dict(original_epoch_id=reset_id,original_request_sha256=reset["request_sha256"],prepared_at=clock.isoformat(),
                    package_sha256=expected_package_sha256,source_template=template,plans=plans,
                    plans_sha256=_fingerprint(plans),metadata_sha256=_fingerprint(metadata))
                meta=deepcopy(self.meta)
                meta.setdefault("paper_target_revision_history",[]).append(dict(revised_at=clock.isoformat(),
                    previous_revision=deepcopy(meta.get("paper_target_revision")),previous_plans={sid:deepcopy(self.plans[sid]) for sid in HGB_STRATEGIES},
                    previous_plan_metadata=deepcopy(self.plan_metadata),previous_close_states=deepcopy(self.close_states),
                    previous_subscription_prewarm=deepcopy(self.meta.get("subscription_prewarm")),previous_last_error=self.meta.get("last_error")))
                meta.update(paper_target_revision=revision,source_refs=deepcopy(loaded["source_refs"]),status="STOPPED",running=False,
                    last_error="",connection_error="",subscription_prewarm={},reason="已按补齐行情更新两套HGB目标；原10000美元现金epoch及历史保持")
                next_plans={**self.plans,**plans};next_states=deepcopy(self.close_states)
                for sid in HGB_STRATEGIES:next_states[sid].update(valuation_basis="PAPER_CASH_EPOCH")
                value={**meta,"plans":next_plans,"book_status":self.book_status,"plan_close_states":next_states,"plan_metadata":metadata}
                with self.db:
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",(json.dumps(value,ensure_ascii=False,allow_nan=False),))
                    self.db.execute("INSERT INTO events VALUES (?,?,?)",(clock.isoformat(),"HGB_PAPER_TARGETS_REVISED",
                        json.dumps(dict(reset_id=reset_id,package_sha256=expected_package_sha256,source_template_id=request["reset_id"],
                            source_archive=loaded["archive"],order_submissions=0),ensure_ascii=False)))
                self.meta,self.plans,self.close_states,self.plan_metadata=meta,next_plans,next_states,metadata
                self.loaded_key,self._prewarm_key=None,None
                return self.state()
        finally:
            self.tick_lock.release()

    def _pending_repair_guard(self):
        from .applied_source import _pending_repair_commit_guard
        row = self.db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
        own = json.loads(row[0]) if row else None
        peer_engine = getattr(self.best_broker, "engine", None)
        peer = peer_engine._get("pending_plan_repair", None) if peer_engine else None
        if own != peer and (own or peer):
            raise ValueError("PENDING_REPAIR_UNFINISHED_OR_BINDING_CHANGED")
        if own and (Path(own["cohort_db"]).resolve() != (self.path / "cohort.sqlite3").resolve()
                    or not self.best_broker or Path(own["broker_db"]).resolve()
                    != (self.best_broker.engine.path / "state.sqlite3").resolve()):
            raise ValueError("PENDING_REPAIR_DATABASE_OWNER_CHANGED")
        _pending_repair_commit_guard(own)

    def _pending_repair_recover(self, repair_id, package_sha):
        """A same-request retry restores only recognised pre/post-crash bindings."""
        from .applied_source import _pending_plan_digest
        row = self.db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
        own = json.loads(row[0]) if row else None
        peer = self.best_broker.engine._get("pending_plan_repair", None)
        if own == peer and (not own or own.get("phase") == "COMMITTED"):
            return
        candidates = [v for v in (own, peer) if v and v.get("repair_id") == repair_id]
        if not candidates:
            raise ValueError("PENDING_REPAIR_UNFINISHED_DIFFERENT_REQUEST")
        marker = candidates[0]
        base = {k: v for k, v in marker.items() if k != "phase"}
        if (marker.get("package_sha256") != package_sha
                or Path(marker["cohort_db"]).resolve() != (self.path / "cohort.sqlite3").resolve()
                or Path(marker["broker_db"]).resolve() != (self.best_broker.engine.path / "state.sqlite3").resolve()
                or any(v != marker.get("previous_marker") and (not v or {k: x for k, x in v.items() if k != "phase"} != base)
                       for v in (own, peer))):
            raise ValueError("PENDING_REPAIR_CRASH_IDENTITY_CHANGED")
        old_c, old_b = marker["previous_cohort"], marker["previous_broker"]
        live_c = json.loads(self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
        live_b = self.best_broker.engine._get("best_plan", None)
        for kind, old, live in (("cohort", old_c, live_c), ("broker", old_b, live_b)):
            if _pending_plan_digest(live, kind) not in {_pending_plan_digest(old, kind), marker["new_hashes"][kind]}:
                raise ValueError("PENDING_REPAIR_CRASH_UNRECOGNISED_PLAN")
        self.best_broker._pending_repair_no_execution(old_c["plan_metadata"])
        if self.best_broker.engine._pending():
            raise ValueError("PENDING_REPAIR_CRASH_PENDING_ORDER")
        self._pending_repair_sql(old_c, old_b, marker.get("previous_marker"))
        self.meta = {k: deepcopy(v) for k, v in old_c.items()
                     if k not in {"plans", "book_status", "plan_close_states", "plan_metadata"}}
        self.plans, self.book_status = deepcopy(old_c["plans"]), deepcopy(old_c["book_status"])
        self.close_states, self.plan_metadata = deepcopy(old_c["plan_close_states"]), deepcopy(old_c["plan_metadata"])
        self.best_broker.plan, self.best_broker.metadata = deepcopy(old_b["plan"]), deepcopy(old_b["metadata"])

    def _pending_repair_checks(self, metadata, clock):
        from .applied_source import LEGACY_POLICY
        broker = self.best_broker
        if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                or self.halt_event.is_set() or broker is None or not broker.stop_event.is_set()
                or (broker.worker and broker.worker.is_alive()) or broker.engine.halt_event.is_set()
                or set(self._active_ids()) != set(HGB_STRATEGIES)
                or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600
                or self.allow_partial_quotes is not True):
            raise ValueError("PENDING_REPAIR_REQUIRES_STOPPED_NORMAL_HGB_OWNERS")
        broker.engine._require_stopped()
        if (self.path.name != "books" or broker.engine.path.name != "moomoo-best"
                or self.path.parent.resolve() != broker.engine.path.parent.resolve()
                or Path(self.source.runtime_root).resolve() != (self.path.parent / "source/local").resolve()
                or Path(broker.source.runtime_root).resolve() != (self.path.parent / "source/moomoo").resolve()):
            raise ValueError("PENDING_REPAIR_ORIGINAL_OWNER_PATHS_REQUIRED")
        if not timestamp(metadata["signal_close_utc"]) <= clock < timestamp(metadata["next_open_utc"]):
            raise ValueError("PENDING_REPAIR_PREOPEN_ONLY")
        if any(metadata.get(key) != expected for key, expected in
               (("execution_delay_minutes", 0), ("execution_window_seconds", 600), ("allow_partial_quotes", True))):
            raise ValueError("PENDING_REPAIR_EXECUTION_WINDOW_CHANGED")
        signal, execution = metadata["signal_date"], metadata["execution_date"]
        for sid, engine in self._active_engines().items():
            engine._require_stopped()
            if (engine.halt_event.is_set() or engine._pending() or engine.mode != "paper" or not engine.paper_only
                    or engine.account_id != "paper-" + sid
                    or engine._get("paper_account_identity", None) != engine.account_id):
                raise ValueError("PENDING_REPAIR_PAPER_ACCOUNT_CHANGED")
            plan = self.plans.get(sid, {})
            if (plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY
                    or plan.get("signal_date") != signal or plan.get("execution_date") != execution
                    or plan.get("valuation_basis") != "SIGNAL_CLOSE" or plan.get("reset_id") or plan.get("execution_mode")):
                raise ValueError("PENDING_REPAIR_NORMAL_LEGACY_PLAN_REQUIRED")
            if any(timestamp(row[0]) >= timestamp(metadata["signal_close_utc"])
                   for row in engine.db.execute("SELECT created_at FROM orders")):
                raise ValueError("PENDING_REPAIR_PAPER_PERIOD_ORDER_EXISTS")
            for table in ("paper_batches", "paper_fills"):
                for row in engine.db.execute("SELECT payload FROM " + table):
                    record = json.loads(row[0])
                    if record.get("signal_date") == signal or record.get("execution_date") == execution:
                        raise ValueError("PENDING_REPAIR_PAPER_EXECUTION_ALREADY_STARTED")
            for record in (self.book_status.get(sid, {}), engine._get("paper_same_day_catchup", {}) or {}):
                if record.get("signal_date") == signal or record.get("execution_date") == execution:
                    raise ValueError("PENDING_REPAIR_PAPER_PROGRESS_EXISTS")
        record = self.meta.get("paper_same_day_catchup", {}) or {}
        if record.get("signal_date") == signal or record.get("execution_date") == execution:
            raise ValueError("PENDING_REPAIR_PAPER_CATCHUP_EXISTS")

    def _pending_repair_sql(self, cohort_value, broker_value, marker):
        """One ordinary transaction; durable PREPARED guards cover WAL crash partials."""
        db = self.db
        db.execute("ATTACH DATABASE ? AS pending_broker", (str(self.best_broker.engine.path / "state.sqlite3"),))
        try:
            db.execute("BEGIN IMMEDIATE")
            for namespace, key, value in (("main", "cohort", cohort_value),
                    ("pending_broker", "best_plan", broker_value),
                    ("main", "pending_plan_repair", marker), ("pending_broker", "pending_plan_repair", marker)):
                db.execute("INSERT OR REPLACE INTO " + namespace + ".settings VALUES (?,?)",
                           (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.execute("DETACH DATABASE pending_broker")

    def repair_pending_targets(self, repair_id, expected_package_sha256, now=None):
        """Revise normal LEGACY pending plans from actual books; no execution permission changes."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        from .applied_source import (LEGACY_POLICY, _pending_repair_request, _pending_source_binding,
                                     _pending_plan_digest, _reference, _json, _state)
        clock, started = _now(now), time.monotonic()
        if (not isinstance(repair_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", repair_id)
                or not isinstance(expected_package_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_package_sha256)):
            raise ValueError("PENDING_REPAIR_REQUEST_INVALID")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("PENDING_REPAIR_WAIT_FOR_WORKER_EXIT")
        try:
            with ExitStack() as locks:
                locks.enter_context(self.lock)
                broker = self.best_broker
                if broker is None:
                    raise ValueError("PENDING_REPAIR_ORIGINAL_BROKER_REQUIRED")
                locks.enter_context(broker.lock)
                locks.enter_context(broker.engine.lock)
                for engine in self._active_engines().values():
                    locks.enter_context(engine.lock)
                self._pending_repair_checks(self.plan_metadata, clock)
                self._pending_repair_recover(repair_id, expected_package_sha256)
                self._pending_repair_guard()
                prior_row = self.db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
                previous_marker = json.loads(prior_row[0]) if prior_row else None
                check = previous_marker
                while check:
                    if check.get("repair_id") == repair_id:
                        if check is not previous_marker or check.get("package_sha256") != expected_package_sha256:
                            raise ValueError("PENDING_REPAIR_ID_REUSED")
                        return self.state()
                    check = check.get("previous_marker")
                metadata = deepcopy(self.plan_metadata)
                signal = metadata["signal_date"]
                old_ref = ((previous_marker or {}).get("paper_archive")
                           if (previous_marker or {}).get("signal_date") == signal else None)
                if not old_ref:
                    path = Path(self.source.runtime_root) / signal / "plans.json"
                    old_ref = _reference(path)
                _reference(old_ref["path"], old_ref["sha256"])
                archived = _json(old_ref["path"])
                if (archived.get("plans") != {sid: self.plans[sid] for sid in HGB_STRATEGIES}
                        or archived.get("source_refs") != metadata.get("source_refs")
                        or archived.get("states") != {sid: _state(self.close_states[sid], signal) for sid in HGB_STRATEGIES}
                        or metadata.get("source_refs", {}).get("selected/package.json", {}).get("sha256") == expected_package_sha256):
                    raise ValueError("PENDING_REPAIR_ORIGINAL_ARCHIVE_OR_NEW_SOURCE_REQUIRED")
                request = _pending_repair_request(dict(repair_id=repair_id, prepared_at=clock.isoformat(), signal_date=signal,
                    execution_date=metadata["execution_date"], next_open_utc=metadata["next_open_utc"],
                    signal_close_utc=metadata["signal_close_utc"], expected_policy_id=LEGACY_POLICY,
                    expected_package_sha256=expected_package_sha256, previous_archive=old_ref), now=clock)
                _pending_source_binding(self.source.status(now=clock), metadata, expected_package_sha256, clock)
                books = self._books_input()
                states = self.source.close_states(books, signal_date=signal)
                if (set(states) != set(HGB_STRATEGIES)
                        or {sid: _state(states[sid], signal) for sid in HGB_STRATEGIES} != archived["states"]):
                    raise ValueError("PENDING_REPAIR_PAPER_ACTUAL_CLOSE_STATE_CHANGED")
                loaded = self.source.load(states, now=clock, repair_request=request)
                _pending_source_binding(loaded, metadata, expected_package_sha256, clock)
                if set(loaded.get("plans", {})) != set(HGB_STRATEGIES):
                    raise ValueError("PENDING_REPAIR_STRATEGIES_CHANGED")
                new_broker, broker_book = broker._pending_repair_prepare(request, metadata, clock)
                finished = clock + timedelta(seconds=time.monotonic() - started)
                self._pending_repair_checks(metadata, finished)
                _pending_source_binding(self.source.status(now=finished), metadata, expected_package_sha256, finished)
                _pending_source_binding(broker.source.status(now=finished), metadata, expected_package_sha256, finished)
                broker._pending_repair_no_execution(request)
                if broker._pending_repair_actual_book() != broker_book:
                    raise ValueError("PENDING_REPAIR_BROKER_BOOK_CHANGED_DURING_PREPARATION")
                if self._books_input() != books:
                    raise ValueError("PENDING_REPAIR_PAPER_BOOK_CHANGED_DURING_PREPARATION")
                new_meta = deepcopy(self.meta)
                new_metadata = {key: deepcopy(loaded.get(key)) for key in ("signal_date", "execution_date", "next_open_utc",
                    "signal_close_utc", "source_refs", "source_date")}
                new_metadata.update(execution_time_utc=loaded["next_open_utc"], execution_delay_minutes=0,
                    execution_window_seconds=600, allow_partial_quotes=True)
                new_meta.update(source_refs=deepcopy(loaded["source_refs"]), status="STOPPED", running=False,
                    reason="已从实际持仓修订尚未执行的同日HGB目标；等待手动恢复自动执行")
                new_plans = {**deepcopy(self.plans), **deepcopy(loaded["plans"])}
                new_states = {**deepcopy(self.close_states), **deepcopy(states)}
                new_cohort = {**new_meta, "plans": new_plans, "book_status": deepcopy(self.book_status),
                    "plan_close_states": new_states, "plan_metadata": new_metadata}
                final_clock = clock + timedelta(seconds=time.monotonic() - started)
                self._pending_repair_checks(metadata, final_clock)
                broker._pending_repair_no_execution(request)
                for source in (self.source, broker.source):
                    _reference(source.status(now=final_clock)["source_refs"]["selected/package.json"]["path"], expected_package_sha256)
                final_clock = clock + timedelta(seconds=time.monotonic() - started)
                self._pending_repair_checks(metadata, final_clock)
                old_cohort = json.loads(self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0])
                old_broker = broker.engine._get("best_plan", None)
                marker = dict(phase="PREPARED", repair_id=repair_id, package_sha256=expected_package_sha256,
                    signal_date=signal, execution_date=metadata["execution_date"], prepared_at=clock.isoformat(),
                    cohort_db=str((self.path / "cohort.sqlite3").resolve()),
                    broker_db=str((broker.engine.path / "state.sqlite3").resolve()),
                    paper_archive=loaded["archive"], broker_archive=new_broker["metadata"]["archive"],
                    previous_paper_archive=old_ref, previous_broker_archive=old_broker["metadata"]["archive"],
                    previous_cohort=old_cohort, previous_broker=old_broker, previous_marker=previous_marker,
                    new_hashes={"cohort": _pending_plan_digest(new_cohort, "cohort"),
                                "broker": _pending_plan_digest(new_broker, "broker")}, order_submissions=0)
                # First best marker then paper marker. Cohort's shared guard sees either side.
                broker.engine._set("pending_plan_repair", marker)
                self.db.execute("INSERT OR REPLACE INTO settings VALUES ('pending_plan_repair',?)", (json.dumps(marker),))
                self.db.commit()
                try:
                    self._pending_repair_sql(new_cohort, new_broker, marker)
                    if (_pending_plan_digest(json.loads(self.db.execute("SELECT value FROM settings WHERE key='cohort'").fetchone()[0]), "cohort") != marker["new_hashes"]["cohort"]
                            or _pending_plan_digest(broker.engine._get("best_plan", None), "broker") != marker["new_hashes"]["broker"]):
                        raise ValueError("PENDING_REPAIR_DURABLE_READBACK_FAILED")
                    self._pending_repair_checks(metadata, clock + timedelta(seconds=time.monotonic() - started))
                    committed = {**marker, "phase": "COMMITTED"}
                    self._pending_repair_sql(new_cohort, new_broker, committed)
                    self._pending_repair_guard()
                    self._pending_repair_checks(metadata, clock + timedelta(seconds=time.monotonic() - started))
                except BaseException:
                    # If power is lost during WAL commits PREPARED remains failclosed;
                    # ordinary errors restore both original bindings before returning.
                    self._pending_repair_sql(old_cohort, old_broker, previous_marker)
                    raise
                self.meta, self.plans, self.close_states, self.plan_metadata = new_meta, new_plans, new_states, new_metadata
                self.loaded_key, self._prewarm_key = None, None
                broker.plan, broker.metadata = deepcopy(new_broker["plan"]), deepcopy(new_broker["metadata"])
                broker.prepared_at, broker._prewarm_key = 0.0, None
                return self.state()
        finally:
            self.tick_lock.release()

    def _scheduled_open(self, value):
        return timestamp(value) + timedelta(minutes=self.execution_delay_minutes)

    def _persist(self, *, event=None):
        with self.lock, self.db:
            value = {**self.meta, "plans": self.plans, "book_status": self.book_status,
                     "plan_close_states": self.close_states, "plan_metadata": self.plan_metadata}
            self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",
                            (json.dumps(value, ensure_ascii=False, allow_nan=False),))
            if event is not None:
                name, detail, clock = event
                self.db.execute("INSERT INTO events VALUES (?,?,?)", (clock.isoformat(), name,
                    json.dumps(detail, ensure_ascii=False, allow_nan=False)))
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
            if method == "tick":
                from .best_broker import BestBroker
                worker = getattr(self.best_broker, "worker", None)
                if isinstance(self.best_broker, BestBroker) and worker is not None and worker.is_alive():
                    return  # The broker worker owns polling and its read-error cooldown.
            getattr(self.best_broker, method)(**kwargs)
            if method == "start":
                with self.lock:
                    self.meta["broker_error"] = ""
                    self._persist()
        except Exception as exc:
            with self.lock:
                self.meta["broker_error"] = str(exc)

    def _current_automatic_completion_policy(self):
        # Replaced as a whole only by the stopped owner; never a second policy registry.
        return self.meta.get("automatic_completion_policy")

    def _published_target_for_conversion(self, sid, signal_date):
        """Read the committed canonical row without broker/cohort lock inversion."""
        if sid not in self._active_ids():
            raise ValueError("PUBLISHED_TARGET_CONVERSION_INACTIVE_OWNER")
        uri = (self.path.resolve() / "cohort.sqlite3").as_uri() + "?mode=ro"
        from contextlib import closing
        with closing(sqlite3.connect(uri, uri=True)) as reader:
            row = reader.execute("SELECT json_extract(value,?),json_extract(value,?) FROM settings WHERE key='cohort'",
                ("$.plans."+sid,"$.book_plan_metadata."+sid)).fetchone()
        if not row or not all(isinstance(value,str) and len(value.encode("utf8"))<=2*1024*1024 for value in row): return None
        plan, metadata = (json.loads(value) for value in row)
        if plan.get("signal_date") != signal_date or metadata.get("signal_date") != signal_date: return None
        return {"plan":plan,"metadata":metadata}

    def _bind_automatic_completion_policy(self):
        for engine in self.engines.values():
            engine.automatic_completion_policy_provider = self._current_automatic_completion_policy
        if self.best_broker is not None:
            self.best_broker.engine.automatic_completion_policy_provider = self._current_automatic_completion_policy
            self.best_broker.published_target_provider = self._published_target_for_conversion

    def authorize_automatic_completion_policy(self, *, enabled, close_buffer_seconds, one_tick_spread, now):
        """One standing authorization; account projections commit before the canonical owner."""
        if (type(enabled) is not bool or type(close_buffer_seconds) is not int
                or close_buffer_seconds != 600 or type(one_tick_spread) is not bool):
            raise ValueError("AUTOMATIC_COMPLETION_POLICY_REQUEST_INVALID")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("AUTOMATIC_COMPLETION_POLICY_WAIT_FOR_TICK")
        try:
            with self.lock, ExitStack() as locks:
                broker = self.best_broker
                desired_clock = self.meta.get("next_ordinary_execution_clock") or {}
                policy_delay = desired_clock.get("execution_delay_minutes", self.execution_delay_minutes)
                policy_window = desired_clock.get("execution_window_seconds", self.execution_window_seconds)
                new_clock = (policy_delay, policy_window) == (25, 1500)
                if (self.closed or self.halt_event.is_set() or not self.stop_event.is_set()
                        or self.worker and self.worker.is_alive()
                        or ("HGB_DIAG_5" not in self._active_ids() if new_clock else set(self._active_ids()) != set(HGB_STRATEGIES))
                        or not new_clock and (self.execution_delay_minutes != 0 or self.execution_window_seconds != 600)
                        or broker is None):
                    raise ValueError("AUTOMATIC_COMPLETION_POLICY_REQUIRES_STOPPED_ORIGINAL_COMPONENT")
                locks.enter_context(broker.lock)
                broker_clock = broker.engine._get("best_next_ordinary_execution_clock", None) or {}
                if (not broker.stop_event.is_set() or broker.worker and broker.worker.is_alive()
                        or ((broker_clock.get("execution_delay_minutes", broker.execution_delay_minutes),
                             broker_clock.get("execution_window_seconds", broker.execution_window_seconds)) != (25, 1500)
                            if new_clock else broker.execution_window_seconds != 600)):
                    raise ValueError("AUTOMATIC_COMPLETION_POLICY_REQUIRES_STOPPED_ORIGINAL_BROKER")
                engines = ([self.engines[sid] for sid in HGB_STRATEGIES] if new_clock else list(self._active_engines().values())) + [broker.engine]
                for engine in engines:
                    locks.enter_context(engine.lock)
                    engine._require_stopped()
                    if engine.halt_event.is_set() or engine._pending():
                        raise ValueError("AUTOMATIC_COMPLETION_POLICY_UNKNOWN_OR_PENDING_ORDER")
                account = broker.engine._get("best_account", None)
                capital = broker.engine._get("best_capital", {})
                if (broker.engine.mode != "moomoo_simulate" or broker.engine.broker is None
                        or broker.engine.account_id != account
                        or str(broker.engine.broker.account_id) != account
                        or capital.get("account_id") != account or capital.get("budget") != 10000
                        or broker.budget != 10000 or time.monotonic() - broker.last_snapshot_at > 60
                        or broker.snapshot.get("funds_only") is not True
                        or broker.snapshot.get("open_orders") != []):
                    raise ValueError("AUTOMATIC_COMPLETION_POLICY_ORIGINAL_ACCOUNT_NOT_RECONCILED")
                clock = _now(now)
                old = self.meta.get("automatic_completion_policy")
                if new_clock and not isinstance(old, dict):
                    raise ValueError("AUTOMATIC_COMPLETION_EXISTING_HGB_AUTHORITY_REQUIRED")
                if new_clock and enabled and (old.get("enabled") is not True or old.get("one_tick_spread") != one_tick_spread):
                    raise ValueError("AUTOMATIC_COMPLETION_CLOCK_UPDATE_MUST_PRESERVE_OLD_LIMITS")
                if (new_clock and broker.strategy_id in old.get("active_strategy_ids", [])
                        and old.get("broker_account_id") != account):
                    raise ValueError("AUTOMATIC_COMPLETION_ORIGINAL_ACCOUNT_CHANGED")
                repair_projection = False
                if old is not None:
                    validate_auto_completion_policy(old)
                    if (old["enabled"] == enabled and old["close_buffer_seconds"] == close_buffer_seconds
                            and old["one_tick_spread"] == one_tick_spread
                            and old["schema_version"] == (2 if new_clock else 1)
                            and old["priority_window_seconds"] == policy_window):
                        digest = _first_execution_sha(old)
                        coherent = all(engine._get("automatic_completion_policy", None) == old
                            and any(_first_execution_sha(json.loads(row[0])) == digest for row in
                                engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
                                    ("AUTOMATIC_COMPLETION_POLICY_AUTHORIZED", old["authorized_at_utc"])))
                            for engine in engines)
                        if coherent:
                            return deepcopy(old)
                        # A failed multi-DB commit must not report a broken projection as success.
                        # Restore only the existing canonical authority, with its unchanged date/limits.
                        repair_projection = True
                if repair_projection:
                    policy = deepcopy(old)
                elif not enabled:
                    if old is None:
                        return None
                    policy = {**old, "enabled": False}
                else:
                    effective = (clock.astimezone(NY).date() + timedelta(days=1)).isoformat()
                    policy = dict(schema_version=2 if new_clock else 1, enabled=True,
                        policy_id="user_auto_completion_" + clock.strftime("%Y%m%dT%H%M%S%f"),
                        reason="USER_EXPLICIT_DAILY_AUTO_COMPLETION", authorized_at_utc=clock.isoformat(),
                        effective_execution_date=effective, evaluation_end_exclusive="2027-01-01",
                        priority_window_seconds=1500 if new_clock else 600, close_buffer_seconds=close_buffer_seconds,
                        one_tick_spread=one_tick_spread, normal_spread_bps=50,
                        max_single_tick_spread_bps=200, quote_max_age_seconds=30,
                        price_deviation_fraction=.02, active_strategy_ids=list(HGB_STRATEGIES),
                        broker_account_id=old["broker_account_id"] if new_clock else account, broker_budget=10000)
                    if new_clock:
                        policy["execution_delay_minutes"] = 25
                validate_auto_completion_policy(policy)
                proposed = {**self.meta, "automatic_completion_policy": policy,
                    "plans": self.plans, "book_status": self.book_status,
                    "plan_close_states": self.close_states, "plan_metadata": self.plan_metadata}
                # Master is entered first, committed last. Partial failure cannot activate new projections.
                with ExitStack() as transactions:
                    transactions.enter_context(self.db)
                    for engine in engines:
                        transactions.enter_context(engine.db)
                        engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                            ("automatic_completion_policy", json.dumps(policy, ensure_ascii=False, allow_nan=False)))
                        engine.db.execute("INSERT INTO audit VALUES (?,?,?)",
                            (policy["authorized_at_utc"], "AUTOMATIC_COMPLETION_POLICY_AUTHORIZED",
                             json.dumps(policy, ensure_ascii=False, allow_nan=False)))
                    self.db.execute("INSERT OR REPLACE INTO settings VALUES ('cohort',?)",
                        (json.dumps(proposed, ensure_ascii=False, allow_nan=False),))
                    self.db.execute("INSERT INTO events VALUES (?,?,?)",
                        (clock.isoformat(), "AUTOMATIC_COMPLETION_POLICY_PROJECTION_REPAIRED" if repair_projection else
                         "AUTOMATIC_COMPLETION_POLICY_AUTHORIZED" if enabled else
                         "AUTOMATIC_COMPLETION_POLICY_DISABLED", json.dumps(policy, ensure_ascii=False)))
                self.meta = {k: v for k, v in proposed.items() if k not in
                    {"plans", "book_status", "plan_close_states", "plan_metadata"}}
                self._bind_automatic_completion_policy()
                return deepcopy(policy)
        finally:
            self.tick_lock.release()

    def _start_ack(self):
        # A control receipt is not a financial snapshot or an execution permission.
        return dict(control_ack="START", applied=True, running=not self.stop_event.is_set(),
            halted=self.halt_event.is_set(), broker_start_requested=self.best_broker is not None,
            broker_error=self.meta.get("broker_error", ""), manual_data_updates=self.manual_data_updates)

    def start(self):
        self._maintenance_start_guard()
        with self.lock:
            requested = self.meta.get("next_ordinary_execution_clock") or {}
            next_pair = (requested.get("execution_delay_minutes", self.execution_delay_minutes),
                requested.get("execution_window_seconds", self.execution_window_seconds))
            policy = self._current_automatic_completion_policy()
            if next_pair == (25, 1500) and policy is not None:
                validate_auto_completion_policy(policy)
                if (policy["enabled"] and set(self._active_ids()) & set(policy["active_strategy_ids"])
                        and policy["schema_version"] != 2):
                    raise ValueError("ORDINARY_CLOCK_SCHEMA2_POLICY_UPDATE_REQUIRED")
            self._pending_repair_guard()
            if self.closed or self._closing:
                raise ValueError("执行器已关闭")
            if self.halt_event.is_set():
                raise ValueError("紧急停止已锁定，不能自动恢复")
            if self.meta.get("paper_reset", {}).get("phase") not in (None, "COMMITTED"):
                raise ValueError("HGB_RESET_UNFINISHED_TRANSACTION")
            if self.worker and self.worker.is_alive():
                return self._start_ack()
            for engine in self._active_engines().values():
                engine.cancel_step.clear()
            self.stop_event.clear()
            self.meta.update(running=True, status="WAITING_SOURCE", reason="等待已完成日信号及计划执行时点")
            self._persist()
            self.worker = threading.Thread(target=self._run, daemon=True, name="applied-paper-cohort")
            self.worker.start()
        self._hook("start")
        with self.lock:
            return self._start_ack()

    def _prepare_published_inputs(self, *, expected_signal_date, now=None):
        """Explicit cache preparation through the existing owners; never run an order cycle."""
        if not self.manual_data_updates:
            raise ValueError("MANUAL_DATA_UPDATES_MODE_REQUIRED")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("MANUAL_CACHE_PREPARATION_OWNER_BUSY")
        try:
            clock = _now(now)
            with self.lock:
                self._pending_repair_guard()
                if (not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                        or self.closed or self.halt_event.is_set() or any(
                            engine.halt_event.is_set() or engine._pending() for engine in self._active_engines().values())
                        or getattr(self, "_execution_charts_job", None) is not None):
                    raise ValueError("MANUAL_CACHE_PREPARATION_REQUIRES_PAUSED_IDLE_OWNERS")
                broker = self.best_broker
                if broker is not None:
                    broker._require_manual_preparation()
                data = self.source.status(now=clock)
                signal, execution, _ = self._metadata(data, clock)
                if (signal != expected_signal_date or data.get("source_date") != signal or data.get("data_gaps")
                        or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}):
                    raise ValueError("MANUAL_CACHE_CURRENT_PUBLISHED_SOURCE_REQUIRED")
                if self.meta.get("strategy_membership_binding"):
                    errors = self._prepare_active_members(data, clock, explicit_update=True)
                else:
                    self._prepare(data, clock, explicit_update=True)
                    errors = {}
                # Publish only clocks supplied and validated by the original source.
                self.meta.update({key: data[key] for key in ("signal_date", "execution_date", "next_open_utc",
                    "signal_close_utc", "next_close_utc", "source_refs", "next_refresh_utc", "refresh_not_before_utc") if key in data})
                self._persist()
                for sid in self._active_ids():
                    frozen = self.meta.get("book_plan_metadata", {}).get(sid, self.plan_metadata)
                    if (not self.plans.get(sid) or frozen.get("signal_date") != signal
                            or frozen.get("execution_date") != execution):
                        errors.setdefault(sid, "CURRENT_FROZEN_PLAN_UNAVAILABLE")
                books = {sid: dict(status="BLOCKED" if sid in errors else "READY",
                    reason=errors.get(sid, ""), signal_date=signal, execution_date=execution) for sid in self._active_ids()}
            broker_result = None
            if broker is not None:
                broker_result = broker.prepare_published_inputs(expected_signal_date=signal, now=clock)
            receipt = dict(action="PREPARE_CURRENT_PUBLISHED_INPUTS", signal_date=signal, execution_date=execution,
                status="PARTIAL" if errors or broker_result and not broker_result.get("prepared") else "READY",
                books=books, broker=broker_result, orders_created=0, running=not self.stop_event.is_set())
            self._event("MANUAL_PUBLISHED_INPUTS_PREPARED", receipt, clock)
            return receipt
        finally:
            self.tick_lock.release()

    def _request_execution_charts(self, *, expected_signal_date, now=None):
        """Explicitly admit the existing job; ordinary ticks only supervise it."""
        if not self.manual_data_updates:
            raise ValueError("MANUAL_DATA_UPDATES_MODE_REQUIRED")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("MANUAL_CACHE_PREPARATION_OWNER_BUSY")
        try:
            clock = _now(now)
            data = self.source.status(now=clock)
            signal, _, _ = self._metadata(data, clock)
            if (signal != expected_signal_date or data.get("source_date") != signal or data.get("data_gaps")
                    or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}):
                raise ValueError("MANUAL_CACHE_CURRENT_PUBLISHED_SOURCE_REQUIRED")
            if self.stop_event.is_set():
                raise ValueError("EXPLICIT_CHART_JOB_REQUIRES_RUNNING_OWNER_FOR_CANCEL_SUPERVISION")
            self._execution_charts_tick(data, clock, explicit_update=True)
            self._persist()
            return dict(action="UPDATE_EXECUTION_CHARTS", orders_created=0,
                execution_charts_update=deepcopy(self.meta.get("execution_charts_update", {})))
        finally:
            self.tick_lock.release()


    def _maintenance_active(self):
        record = getattr(self, "_maintenance", None)
        return isinstance(record, dict) and record.get("phase") != "FINISHED"

    def _maintenance_start_guard(self):
        if self._maintenance_active() and (self._maintenance.get("cancel_requested")
                or getattr(self, "_maintenance_restore_thread", None) != threading.get_ident()):
            raise ValueError("MANUAL_MAINTENANCE_ACTIVE")

    def _maintenance_match(self, maintenance_id):
        record = getattr(self, "_maintenance", None)
        if (not isinstance(record, dict) or record.get("maintenance_id") != maintenance_id
                or record.get("phase") == "FINISHED"):
            raise ValueError("MANUAL_MAINTENANCE_ID_REQUIRED")
        return record

    def _maintenance_user_stop(self):
        with self._maintenance_lock:
            if self._maintenance_active():
                self._maintenance.update(restore_requested=False, cancel_requested=True,
                    reason="USER_STOP_OVERRIDES_MAINTENANCE_RESUME", phase="CANCELLED")

    def _maintenance_workers_drained(self):
        broker = self.best_broker
        return all(worker is None or not worker.is_alive() for worker in
            (self.worker, getattr(broker, "worker", None))) and not self.tick_lock.locked()

    def _maintenance_cleanup_verified(self):
        broker = self.best_broker
        return (self._maintenance_workers_drained() and getattr(self, "_execution_charts_job", None) is None
            and not _worker_quarantine_reason() and all(getattr(owner, "_manual_inference_quarantine_lock", None) is None
                for owner in (self, broker)) and not (self._maintenance or {}).get("operation_active"))

    def _maintenance_source_identity(self, data):
        return _fingerprint({key: data.get(key) for key in ("signal_date", "execution_date", "source_date",
            "next_open_utc", "signal_close_utc", "next_close_utc", "source_refs")})

    def _maintenance_plan_identity(self):
        broker = self.best_broker
        return _fingerprint(dict(active_ids=list(self._active_ids()),
            binding=self.meta.get("strategy_membership_binding"), plans=self.plans,
            book_metadata=self.meta.get("book_plan_metadata", {}), account_id=broker.engine.account_id,
            strategy_id=broker.strategy_id, budget=broker.budget, broker_book=broker._book(), broker_plan=broker.plan,
            broker_metadata=broker.metadata))

    def _maintenance_window_bounds(self, data, clock):
        # The original source supplies dates; original owners supply deadlines.
        self._metadata(data, clock)
        # Maintenance protects the audited future window even before acquisition.
        # It does not qualify an input or activate the deferred trading clock.
        next_clock = self._next_ordinary_clock(data, clock, explicit_update=True, maintenance_projection=True)
        opening = self._scheduled_open(data["next_open_utc"])
        projected = (timestamp(data["next_open_utc"]) + timedelta(minutes=next_clock["execution_delay_minutes"])
            if next_clock is not None else opening)
        bounds = []
        for sid in self._active_ids():
            policy, end = self._book_execution_window(sid, data, clock,
                **({"maintenance_clock": next_clock} if next_clock is not None else {}))
            start = opening if policy is not None and policy.get("schema_version", 1) != 2 else projected
            bounds.append((start, end))
        # Projection adds future protection; it never removes an existing bound.
        bounds.extend((opening, end) for end in (self._first_execution_end(data, clock),
            self._catchup_end(data, clock)) if end is not None)
        if next_clock is not None:
            bounds.append((opening, opening + timedelta(seconds=self.execution_window_seconds)))
        broker = self.best_broker
        if broker is not None:
            ordinary = broker._scheduled_open(data["next_open_utc"])
            bounds.append((ordinary, ordinary + timedelta(seconds=broker.execution_window_seconds)))
            broker_clock = broker._next_ordinary_clock(data["signal_date"])
            if broker_clock is not None:
                future = timestamp(data["next_open_utc"]) + timedelta(minutes=broker_clock["execution_delay_minutes"])
                bounds.append((future, future + timedelta(seconds=broker_clock["execution_window_seconds"])))
            if broker.plan and broker.metadata.get("next_open_utc"):
                bounds.append((broker._scheduled_open(broker.metadata["next_open_utc"]), broker._execution_end()))
        return bounds

    def _maintenance_financial_idle(self, data, clock):
        """Explicit paused maintenance; ordinary after-windows rules remain unchanged."""
        if self.closed or self._closing:
            raise ValueError("MANUAL_MAINTENANCE_OWNER_CLOSED")
        if any(start <= clock < end for start, end in self._maintenance_window_bounds(data, clock)):
            raise ValueError("MANUAL_MAINTENANCE_FINANCIAL_WINDOW_ACTIVE")
        if self.halt_event.is_set() or any(engine.halt_event.is_set() or engine._pending()
                for engine in self._active_engines().values()):
            raise ValueError("MANUAL_MAINTENANCE_PENDING_UNKNOWN_OR_HALT")
        broker = self.best_broker
        if broker is None:
            raise ValueError("MANUAL_MAINTENANCE_ORIGINAL_SIM_REQUIRED")
        with broker.lock:
            broker._require_original_manual_account()
            if broker.engine.halt_event.is_set() or broker.engine._pending():
                raise ValueError("MANUAL_MAINTENANCE_PENDING_UNKNOWN_OR_HALT")
            broker._accept_snapshot(broker.engine.broker.snapshot([], include_quotes=False))
            if broker.engine._pending():
                raise ValueError("MANUAL_MAINTENANCE_PENDING_UNKNOWN_OR_HALT")

    def _maintenance_watch_bindings(self):
        return dict(active_ids=list(self._active_ids()), account_id=self.best_broker.engine.account_id,
            strategy_id=self.best_broker.strategy_id, budget=self.best_broker.budget)

    def _maintenance_watchdog_reason(self, record):
        # Polling reads only admitted clocks and existing owners; no source/SDK/model call.
        clock = _now()
        if any(timestamp(start) <= clock < timestamp(end) for start, end in record.get("watch_windows", [])):
            return "MANUAL_MAINTENANCE_FINANCIAL_WINDOW_ACTIVE"
        try:
            current = self._maintenance_watch_bindings()
            changed = current != record.get("watch_bindings")
        except ValueError as exc:
            code = str(exc)
            record.setdefault("watchdog_diagnostic", dict(kind="BINDING_VALIDATION_ERROR",
                error_code=code if code == "SHOWCASE_ROSTER_ORIGINAL_V1_BINDING_CHANGED"
                    or re.fullmatch(r"[A-Z][A-Z_]{0,63}", code) else "UNKNOWN"))
            return "MANUAL_MAINTENANCE_QUEUED_BINDING_CHANGED"
        if changed:
            previous = record.get("watch_bindings")
            record.setdefault("watchdog_diagnostic", dict(kind="BINDING_SNAPSHOT_CHANGED",
                changed_fields=[key for key in ("active_ids", "account_id", "strategy_id", "budget")
                    if not isinstance(previous, dict) or not isinstance(current, dict)
                    or key not in previous or key not in current or current[key] != previous[key]]))
            return "MANUAL_MAINTENANCE_QUEUED_BINDING_CHANGED"
        if (self.closed or self._closing or self.halt_event.is_set() or any(engine.halt_event.is_set() or engine._pending()
                for engine in (self.engines[sid] for sid in record["watch_bindings"]["active_ids"])) or self.best_broker.engine.halt_event.is_set()
                or self.best_broker.engine._pending()):
            return "MANUAL_MAINTENANCE_PENDING_UNKNOWN_OR_HALT"
        return None

    def _maintenance_no_heavy_owner(self):
        from .applied_source import _WORKER_LOCK
        if _worker_quarantine_reason() or _WORKER_LOCK.locked():
            raise ValueError("MANUAL_MAINTENANCE_SOURCE_OWNER_BUSY")
        # Probe the same OS authority; do not retain it over child calls that own it.
        with _manual_inference_update(self, self.source):
            pass

    def begin_manual_maintenance(self, *, maintenance_id, now=None):
        if not self.manual_data_updates or not isinstance(maintenance_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", maintenance_id):
            raise ValueError("MANUAL_MAINTENANCE_MODE_AND_ID_REQUIRED")
        with self._maintenance_lock:
            if isinstance(self._maintenance, dict) and self._maintenance["maintenance_id"] == maintenance_id:
                return self.maintenance_status()
            if self._maintenance_active():
                if self._maintenance["maintenance_id"] == maintenance_id:
                    return self.maintenance_status()
                raise ValueError("MANUAL_MAINTENANCE_ACTIVE")
            broker = self.best_broker
            if broker is None:
                raise ValueError("MANUAL_MAINTENANCE_ORIGINAL_SIM_REQUIRED")
            original = dict(cohort=not self.stop_event.is_set(), broker=not broker.stop_event.is_set())
            if original["cohort"] != original["broker"]:
                raise ValueError("MANUAL_MAINTENANCE_HALF_RUNNING_REJECTED")
            self._maintenance = dict(maintenance_id=maintenance_id, phase="GUARDING", operation_active=True,
                original_running=original, began_at_utc=_now(now).isoformat(), restore_requested=original["cohort"], cancel_requested=False,
                prepared=False, main_status="NOT_CHECKED", main_end=None, reason="")
            broker._maintenance_owner = self
        # Suspend new sends immediately. Failure stays paused; never recover old intent implicitly.
        self.stop_event.set(); broker.stop_event.set()
        for engine in self.engines.values():
            engine.cancel_step.set()
        broker.engine.cancel_step.set()
        try:
            clock = _now(now)
            data = self.source.status(now=clock)
            clock = _now(now)
            self._maintenance_financial_idle(data, clock)
            if getattr(self, "_execution_charts_job", None) is not None:
                raise ValueError("MANUAL_MAINTENANCE_CHART_OWNER_BUSY")
            self._maintenance_no_heavy_owner()
            self.stop(scalar=True, _maintenance=True)
            with self._maintenance_lock:
                self._maintenance.update(phase="DRAINING", operation_active=False)
            self._event("MANUAL_MAINTENANCE_BEGAN", dict(maintenance_id=maintenance_id, original_running=original), clock)
            return self.maintenance_status()
        except Exception as exc:
            with self._maintenance_lock:
                self._maintenance.update(phase="FAILED", reason=str(exc), restore_requested=False, operation_active=False)
            self.stop(scalar=True, _maintenance=True)
            raise

    def maintenance_status(self):
        """Control receipt only; no cached view, source query, model or inferred completion."""
        with self._maintenance_lock:
            record = getattr(self, "_maintenance", None)
            if not isinstance(record, dict):
                return dict(schema="MANUAL_DAILY_MAINTENANCE_V1", maintenance_id=None, phase="NONE", active=False)
            job = getattr(self, "_execution_charts_job", None)
            if job is not None and record.get("watch_windows"):
                reason = self._maintenance_watchdog_reason(record)
                if reason:
                    record.update(cancel_requested=True, restore_requested=False, phase="FAILED", reason=reason)
            if record.get("cancel_requested") and job is not None:
                try:
                    self._cancel_execution_charts()
                except RuntimeError as exc:
                    record["reason"] = str(exc)
                job = getattr(self, "_execution_charts_job", None)
            if job is not None:
                code = job.poll()
                if code is not None and type(code) is not int:
                    record.update(restore_requested=False, phase="FAILED", reason="MAIN_CHART_WORKER_EXIT_CODE_INVALID")
                elif code is not None:
                    outcome = job.result() if callable(getattr(job, "result", None)) else {}
                    def summary(value):
                        if not isinstance(value, dict):
                            return {}
                        result = {}
                        if type(value.get("exit_code")) is int:
                            result["exit_code"] = value["exit_code"]
                        if type(value.get("reason")) is str:
                            result["reason"] = value["reason"][:500]
                        for key in ("resource_blocked", "cancelled"):
                            if type(value.get(key)) is bool:
                                result[key] = value[key]
                        return result
                    receipt = summary(outcome)
                    receipt["exit_code"] = code  # The owned job's poll, not an untrusted payload, controls completion.
                    stages = outcome.get("stages") if isinstance(outcome, dict) else None
                    if isinstance(stages, dict):
                        projected = {key: summary(stages[key]) for key in ("legacy", "main") if key in stages}
                        if projected:
                            receipt["stages"] = projected
                    main = receipt.get("stages", {}).get("main", {})
                    for key in ("reason", "resource_blocked"):
                        if key in main:
                            receipt[key] = main[key]
                    self._execution_charts_job = None  # Original poll proves owned-tree cleanup.
                    record.update(job_exit_code=code, main_status="AWAITING_OWNER_RECEIPT" if code == 0 else "FAILED",
                        phase="CANCELLED" if record.get("cancel_requested") else "CHARTS_FINISHED" if code == 0 else "FAILED")
                    if code != 0:
                        reason = "MAIN_CHART_WORKER_NOT_VERIFIED_READY:" + str(code)
                        if receipt.get("reason"):
                            reason = (reason + ":" + receipt["reason"])[:500]
                        record.update(restore_requested=False, reason=reason)
                    if "resource_blocked" in receipt:
                        record["resource_blocked"] = receipt["resource_blocked"]
                    record["job_result"] = receipt
            drained = self._maintenance_workers_drained()
            clean = self._maintenance_cleanup_verified()
            if record["phase"] == "DRAINING" and clean:
                record["phase"] = "PAUSED"
            fields = ("maintenance_id", "phase", "began_at_utc", "original_running", "restore_requested", "operation_active",
                "prepared", "prepare_receipt", "signal_date", "execution_date", "main_status", "main_end", "main_receipt", "reason", "job_exit_code", "resumed",
                "cleanup_verified_before_resume", "job_result", "resource_blocked", "watchdog_diagnostic")
            return dict(schema="MANUAL_DAILY_MAINTENANCE_V1", **{key: deepcopy(record[key]) for key in fields if key in record},
                active=record["phase"] != "FINISHED", workers_drained=drained,
                current_running=dict(cohort=not self.stop_event.is_set(), broker=not self.best_broker.stop_event.is_set()),
                job_active=getattr(self, "_execution_charts_job", None) is not None, cleanup_verified=clean)

    def prepare_published_inputs(self, *, expected_signal_date, maintenance_id=None, now=None):
        if not self._maintenance_active():
            if maintenance_id is not None:
                raise ValueError("MANUAL_MAINTENANCE_ID_REQUIRED")
            return self._prepare_published_inputs(expected_signal_date=expected_signal_date, now=now)
        with self._maintenance_lock:
            record = self._maintenance_match(maintenance_id)
            if record["phase"] != "PAUSED" or not self._maintenance_cleanup_verified() or record.get("cancel_requested"):
                raise ValueError("MANUAL_MAINTENANCE_REQUIRES_DRAINED_PAUSED_OWNERS")
            record.update(phase="PREPARING", operation_active=True)
        try:
            receipt = self._prepare_published_inputs(expected_signal_date=expected_signal_date, now=now)
            with self._maintenance_lock:
                ready = (receipt.get("status") == "READY" and set(receipt.get("books", {})) == set(self._active_ids())
                    and all(value.get("status") == "READY" for value in receipt["books"].values())
                    and isinstance(receipt.get("broker"), dict) and receipt["broker"].get("prepared") is True
                    and not record.get("cancel_requested"))
                record.update(prepare_receipt=deepcopy(receipt), prepared=ready, signal_date=receipt.get("signal_date"),
                    execution_date=receipt.get("execution_date"), phase="PAUSED" if ready else "FAILED")
                if ready:
                    record.update(source_identity=self._maintenance_source_identity({**self.meta, "source_date": receipt["signal_date"]}), plan_identity=self._maintenance_plan_identity())
                else:
                    record.update(restore_requested=False, reason="MANUAL_MAINTENANCE_CURRENT_PREPARATION_NOT_READY")
            return receipt
        except Exception as exc:
            with self._maintenance_lock:
                record.update(phase="FAILED", restore_requested=False, reason=str(exc))
            raise
        finally:
            with self._maintenance_lock:
                record["operation_active"] = False

    def request_execution_charts(self, *, expected_signal_date, maintenance_id=None, now=None, finite_ca_admission_ref=None):
        finite_ca_admission_ref = deepcopy(finite_ca_admission_ref)
        if not self._maintenance_active():
            if finite_ca_admission_ref is not None:
                raise ValueError('FINITE_CA_REQUIRES_MANUAL_MAINTENANCE')
            if maintenance_id is not None:
                raise ValueError("MANUAL_MAINTENANCE_ID_REQUIRED")
            return self._request_execution_charts(expected_signal_date=expected_signal_date, now=now)
        with self._maintenance_lock:
            record = self._maintenance_match(maintenance_id)
            if (record["phase"] != "PAUSED" or not record.get("prepared") or record.get("cancel_requested")
                    or record.get("signal_date") != expected_signal_date or not self._maintenance_cleanup_verified()):
                raise ValueError("MANUAL_MAINTENANCE_CURRENT_PREPARATION_REQUIRED")
            record.update(operation_active=True, phase="CHARTS_PREFLIGHT")
        try:
            clock = _now(now)
            data = self.source.status(now=clock)
            if self._maintenance_source_identity(data) != record["source_identity"]:
                raise ValueError("MANUAL_MAINTENANCE_PREPARED_SOURCE_CHANGED")
            self._maintenance_financial_idle(data, _now(now))
            self._maintenance_no_heavy_owner()
            main = self.source.main_execution_charts_status(now=clock, **(
                {'finite_ca_admission_ref': finite_ca_admission_ref} if finite_ca_admission_ref is not None else {}))
            context = self._validate_main_charts_metadata(main, clock)
            if context.get('finite_ca_admission_ref') != finite_ca_admission_ref:
                raise ValueError('MAIN_CHART_FINITE_ADMISSION_IDENTITY_CHANGED')
            if main["status"] == "BLOCKED":
                receipt = {"status": "BLOCKED"}
                if type(main.get("reason")) is str:
                    receipt["reason"] = main["reason"][:500]
                if type(main.get("resource_blocked")) is bool:
                    receipt["resource_blocked"] = main["resource_blocked"]
                with self._maintenance_lock:
                    record.update(main_status="BLOCKED", main_receipt=receipt)
                    if "resource_blocked" in receipt:
                        record["resource_blocked"] = receipt["resource_blocked"]
                raise ValueError(receipt.get("reason") or "MAIN_CHART_SOURCE_NOT_QUALIFIED")
            if main.get("end") != expected_signal_date:
                raise ValueError("MANUAL_MAINTENANCE_MAIN_CURRENT_SESSION_REQUIRED")
            with self._maintenance_lock:
                if record.get("cancel_requested"):
                    raise ValueError("MANUAL_MAINTENANCE_CANCELLED")
                record.update(main_status=main["status"], main_end=main["end"], main_context=context,
                    main_receipt={key:deepcopy(main[key]) for key in ("status", "end", "context", "manifest_ref") if key in main})
                if main["status"] == "READY":
                    record["phase"] = "READY"
                else:
                    admitted = _now(now)
                    bounds = self._maintenance_window_bounds(data, admitted)
                    if any(start <= admitted < end for start, end in bounds):
                        raise ValueError("MANUAL_MAINTENANCE_FINANCIAL_WINDOW_ACTIVE")
                    record.update(watch_windows=[(start.isoformat(), end.isoformat()) for start, end in bounds],
                        watch_bindings=self._maintenance_watch_bindings())
                    self._execution_charts_job = self.source.start_execution_charts(legacy=False, main_request=main["request"])
                    record["phase"] = "CHARTS_RUNNING"
            return dict(action="UPDATE_EXECUTION_CHARTS", maintenance_id=maintenance_id,
                orders_created=0, main_status=main["status"], main_end=main["end"])
        except Exception as exc:
            with self._maintenance_lock:
                record.update(phase="FAILED", restore_requested=False, reason=str(exc))
            raise
        finally:
            with self._maintenance_lock:
                record["operation_active"] = False

    def end_manual_maintenance(self, *, maintenance_id, abort=False, now=None):
        if type(abort) is not bool:
            raise ValueError("MANUAL_MAINTENANCE_ABORT_BOOLEAN_REQUIRED")
        with self._maintenance_lock:
            record = getattr(self, "_maintenance", None)
            if isinstance(record, dict) and record.get("maintenance_id") == maintenance_id and record.get("phase") == "FINISHED":
                return self.maintenance_status()
            record = self._maintenance_match(maintenance_id)
            if abort:
                record.update(restore_requested=False, cancel_requested=True)
            # Check and reserve the one operation under the same owner lock.
            status = self.maintenance_status()
            if not status["cleanup_verified"] or status["operation_active"]:
                raise ValueError("MANUAL_MAINTENANCE_CLEANUP_PENDING")
            record["operation_active"] = True
        try:
            if not abort and not record.get("cancel_requested"):
                if not record.get("prepared") or record.get("phase") not in {"READY", "CHARTS_FINISHED"}:
                    raise ValueError("MANUAL_MAINTENANCE_QUALIFIED_COMPLETION_REQUIRED")
                clock = _now(now)
                data = self.source.status(now=clock)
                if self._maintenance_source_identity(data) != record["source_identity"]:
                    raise ValueError("MANUAL_MAINTENANCE_PREPARED_SOURCE_OR_ACCOUNT_CHANGED")
                self._maintenance_financial_idle(data, _now(now))
                if self._maintenance_plan_identity() != record["plan_identity"]:
                    raise ValueError("MANUAL_MAINTENANCE_PREPARED_SOURCE_OR_ACCOUNT_CHANGED")
                self._maintenance_no_heavy_owner()
                finite_ref = record.get('main_context', {}).get('finite_ca_admission_ref')
                main = self.source.main_execution_charts_status(now=clock, **(
                    {'finite_ca_admission_ref': finite_ref} if finite_ref is not None else {}))
                current_context = self._validate_main_charts_metadata(main, clock)
                if current_context.get('finite_ca_admission_ref') != finite_ref:
                    raise ValueError('MAIN_CHART_FINITE_ADMISSION_IDENTITY_CHANGED')
                if main["status"] != "READY" or main.get("end") != record["signal_date"]:
                    raise ValueError("MANUAL_MAINTENANCE_MAIN_CURRENT_RECEIPT_REQUIRED")
                record.update(main_status="READY", main_end=main["end"],
                    main_receipt={key:deepcopy(main[key]) for key in ("status", "end", "context", "manifest_ref") if key in main})
            restore = bool(record.get("restore_requested") and not record.get("cancel_requested") and not abort)
            if restore:
                self._maintenance_restore_thread = threading.get_ident()
                try:
                    self.start()  # Original coupled lifecycle and all original execution permissions.
                finally:
                    self._maintenance_restore_thread = None
            with self._maintenance_lock:
                # A stop between an original start guard and its event.clear must win.
                revoked = (record.get("cancel_requested") or not record.get("restore_requested")
                    or self.halt_event.is_set() or self.best_broker.engine.halt_event.is_set())
                if restore and revoked:
                    self.stop(scalar=True, _maintenance=True)
                    restore = False
                elif restore and (self.stop_event.is_set() or self.best_broker.stop_event.is_set() or self.meta.get("broker_error")):
                    raise ValueError("MANUAL_MAINTENANCE_ORIGINAL_COUPLED_START_FAILED")
                record.update(phase="FINISHED", resumed=restore, cleanup_verified_before_resume=True, current_running=dict(
                    cohort=not self.stop_event.is_set(), broker=not self.best_broker.stop_event.is_set()), operation_active=False)
            self._event("MANUAL_MAINTENANCE_FINISHED", dict(maintenance_id=maintenance_id, resumed=restore,
                main_status=record.get("main_status"), main_end=record.get("main_end")), _now(now))
            return self.maintenance_status()
        except Exception as exc:
            record.update(phase="FAILED", restore_requested=False, reason=str(exc))
            self.stop(scalar=True, _maintenance=True)
            raise
        finally:
            with self._maintenance_lock:
                record["operation_active"] = False

    def _cancel_execution_charts(self):
        with self.lock:
            job = getattr(self, "_execution_charts_job", None)
        if job is None:
            return
        # Join outside the Cohort lock. Keep ownership if cleanup is still pending.
        try:
            job.cancel()
        except RuntimeError:
            probe = getattr(job,"quarantine_reason",None)
            reason = probe() if callable(probe) else None
            if isinstance(reason,str) and reason:
                with self.lock:
                    previous = self.meta.get("execution_charts_update", {})
                    self.meta["execution_charts_update"] = {**previous,"status":"QUARANTINED","error":reason}
                    if not self.closed:
                        self._persist()
            raise
        with self.lock:
            if getattr(self, "_execution_charts_job", None) is job:
                self._execution_charts_job = None
                previous = self.meta.get("execution_charts_update", {})
                self.meta["execution_charts_update"] = {**previous, "status": "CANCELLED", "error": ""}
                if not self.closed:
                    self._persist()

    def stop(self, *, scalar=False, _maintenance=False):
        self.stop_event.set()  # Signal before any maintenance or source lock.
        if not _maintenance:
            self._maintenance_user_stop()
        self.stop_event.set()  # Abort before waiting for any book or data-source lock.
        for engine in self.engines.values():
            engine.cancel_step.set()
        self._maintenance_stopping_thread = threading.get_ident() if _maintenance else None
        try:
            self._hook("stop")
        finally:
            self._maintenance_stopping_thread = None
        with self.lock:
            self.meta.update(running=False, status="HALTED" if self.halt_event.is_set() else "STOPPED",
                             reason="已停止；保留纸面持仓和成交记录")
            if not self.closed:
                self._persist()
        self._cancel_execution_charts()  # Resource cleanup cannot delay original financial stop.
        return dict(control_ack="STOP", applied=True, running=False) if scalar else self.state()

    @staticmethod
    def _book_source_data(sid, data):
        """Compare this book's independently verified immutable source scope."""
        current = data.get("source_refs")
        if not isinstance(current, dict):
            return data
        from scripts.research.a2.inference.consensus_paper import PAPER_CURRENT_IDS
        new_ids = set(PAPER_CURRENT_IDS)
        common = {key: value for key, value in current.items() if key.split("/", 1)[0] not in new_ids}
        if sid in new_ids and data.get("candidate_source_scope") == "PAPER_CANDIDATE_REFS_V1":
            status = data.get("strategy_status", {}).get(sid, {})
            prefix = sid + "/"
            selected = {key[len(prefix):]: value for key, value in current.items() if key.startswith(prefix)}
            if status.get("status") != "READY" or status.get("signal_date") != data.get("signal_date") or not selected:
                raise ValueError(status.get("reason") or "FROZEN_BOOK_SOURCE_PROOF_UNAVAILABLE:" + sid)
            return {**data, "source_refs": selected}
        return {**data, "source_refs": common}

    @staticmethod
    def _match_source_refs(frozen, data, reason):
        """Status verifies its current subset without replacing complete frozen plan refs."""
        current = data.get("source_refs")
        required = {"frozen_calendar", "session_hours_rules", "daily/report.json", "selected/package.json",
                    "selected/current_report.json", "current/features.parquet"}
        if (not isinstance(frozen, dict) or not frozen or not isinstance(current, dict) or not current
                or (required.intersection(frozen) and not required.issubset(current))
                or any(key not in frozen or frozen[key] != value for key, value in current.items())):
            raise ValueError(reason)
        return frozen

    def _catchup_source_refs(self, data):
        return self._match_source_refs(self.plan_metadata.get("source_refs"), data, "PAPER_CATCHUP_SOURCE_CHANGED")

    def _catchup_end(self, data, clock):
        original = self.meta.get("paper_same_day_catchup")
        renewal = self.meta.get("paper_same_day_catchup_renewal")
        renewed = isinstance(renewal, dict) and renewal.get("signal_date") == data["signal_date"]
        record = renewal if renewed else original
        if (not isinstance(record, dict) or record.get("signal_date") != data["signal_date"]
                or record.get("execution_date") != data["execution_date"]
                or clock.astimezone(NY).date().isoformat() != data["execution_date"]):
            return None
        if clock >= timestamp(record["deadline_utc"]):
            return None  # This recorded permission cannot reopen an expired paper window.
        if renewed and (not isinstance(original, dict)
                or record.get("expected_prior_sha256") != hashlib.sha256(_bytes(original)).hexdigest()):
            raise ValueError("PAPER_CATCHUP_RENEWAL_PRIOR_CHANGED")
        permission_key = "paper_same_day_catchup_renewal" if renewed else "paper_same_day_catchup"
        full_refs = self._catchup_source_refs(data)
        if (not self.allow_partial_quotes or data.get("data_gaps")
                or any(data.get(key) != self.plan_metadata.get(key) for key in
                       ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                or set(record.get("books", {})) != set(self._active_ids())):
            raise ValueError("PAPER_CATCHUP_SOURCE_CHANGED")
        opening = timestamp(self.plan_metadata["execution_time_utc"])
        end = opening + timedelta(seconds=self.execution_window_seconds)
        for sid, engine in self._active_engines().items():
            permission = record["books"][sid]
            if engine._get(permission_key, None) != permission:
                raise ValueError("PAPER_CATCHUP_BOOK_PERMISSION_CHANGED")
            batch_id = engine._paper_batch_id(sid, data["signal_date"], data["execution_date"])
            row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
            deadline = engine._paper_catchup_end(permission, strategy_id=sid, plan=self.plans[sid],
                batch=json.loads(row[0]) if row else None, batch_id=batch_id, opening=opening,
                closing=timestamp(data["signal_close_utc"]), signal_date=data["signal_date"],
                execution_date=data["execution_date"], source_refs=full_refs, clock=clock, original_end=end)
            if deadline != timestamp(record["deadline_utc"]) or timestamp(permission["next_close_utc"]) != timestamp(data["next_close_utc"]):
                raise ValueError("PAPER_CATCHUP_DEADLINE_CHANGED")
        return timestamp(record["deadline_utc"])

    def _closed_reset_books(self, data, clock):
        """Keep fully committed reset books on their original decision after its windows."""
        reset = self.meta.get("paper_reset")
        execution = data["execution_date"]
        opening = self._scheduled_open(data["next_open_utc"])
        if (not self.allow_partial_quotes or not reset or reset["request"]["signal_date"] != data["signal_date"]
                or clock < opening + timedelta(seconds=self.execution_window_seconds)
                or not all(self._executed(sid, execution) for sid in self._active_ids())):
            return False
        record = self.meta.get("paper_same_day_catchup")
        if (isinstance(record, dict) and record.get("signal_date") == data["signal_date"]
                and clock < timestamp(record["deadline_utc"])):
            return False
        expected = self._initial_hgb_target_plans(reset)
        if (reset.get("phase") != "COMMITTED" or data.get("data_gaps")
                or any(data.get(key) != self.plan_metadata.get(key) for key in
                       ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                or any(self.plans.get(sid) != expected[sid]
                       or self.engines[sid]._get("paper_epoch_id", None) != reset["request"]["reset_id"]
                       for sid in self._active_ids())):
            raise ValueError("HGB_RESET_INITIAL_FROZEN_PLAN_CHANGED")
        for sid, engine in self._active_engines().items():
            batch_id = engine._paper_batch_id(sid, data["signal_date"], execution)
            row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
            batch = json.loads(row[0]) if row else {}
            if (engine._pending() or batch.get("status") != "EXECUTED" or batch.get("source_plan") != self.plans[sid]
                    or batch.get("source_plan_sha256") != hashlib.sha256(_bytes(self.plans[sid])).hexdigest()
                    or batch.get("source_refs") != self.plan_metadata.get("source_refs")):
                raise ValueError("HGB_RESET_INITIAL_FROZEN_PLAN_CHANGED")
            if isinstance(record, dict) and record.get("signal_date") == data["signal_date"]:
                permission = record["books"][sid]
                if engine._get("paper_same_day_catchup", None) != permission:
                    raise ValueError("PAPER_CATCHUP_BOOK_PERMISSION_CHANGED")
                deadline = engine._paper_catchup_end(permission, strategy_id=sid, plan=self.plans[sid],
                    batch=batch, batch_id=batch_id, opening=opening, closing=timestamp(data["signal_close_utc"]),
                    signal_date=data["signal_date"], execution_date=execution,
                    source_refs=self.plan_metadata["source_refs"], clock=clock,
                    original_end=opening + timedelta(seconds=self.execution_window_seconds))
                if deadline != timestamp(record["deadline_utc"]):
                    raise ValueError("PAPER_CATCHUP_DEADLINE_CHANGED")
        old, live = self.plan_metadata.get("source_refs", {}), data.get("source_refs", {})
        if old.get("selected/package.json") != live.get("selected/package.json"):
            from .best_broker import BestBroker
            revision = self.meta.get("paper_target_revision")
            archive = revision["source_template"]["loaded"]["archive"] if revision else reset["loaded"]["archive"]
            BestBroker._closed_history_binding({sid: self.plans[sid] for sid in self._active_ids()},
                self.plan_metadata, data, archive)
        else:
            self._match_source_refs(old, data, "HGB_RESET_INITIAL_SOURCE_CHANGED")
        return True

    def _first_execution_end(self, data, clock):
        group = self.meta.get("paper_first_execution")
        if not isinstance(group, dict) or group.get("signal_date") != data.get("signal_date"):
            return None
        committed = self.db.execute("SELECT value FROM settings WHERE key=?",
            ("paper_first_execution:" + group["signal_date"],)).fetchone()
        if not committed or json.loads(committed[0]) != group:
            raise ValueError("PAPER_FIRST_EXECUTION_GROUP_NOT_DURABLY_COMMITTED")
        if (set(self._active_ids()) != set(HGB_STRATEGIES) or not self.allow_partial_quotes
                or set(group.get("books", {})) != set(HGB_STRATEGIES)
                or data.get("data_gaps") or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                or any(data.get(k) != self.plan_metadata.get(k) for k in
                    ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
            raise ValueError("PAPER_FIRST_EXECUTION_GROUP_CHANGED")
        continuation = self.meta.get("paper_first_continuation")
        if not isinstance(continuation, dict) or continuation.get("signal_date") != group["signal_date"]:
            continuation = None
        if continuation is not None:
            row = self.db.execute("SELECT value FROM settings WHERE key=?",
                ("paper_first_continuation:" + group["signal_date"],)).fetchone()
            if (not row or json.loads(row[0]) != continuation
                    or continuation.get("prior_group_sha256") != _first_execution_sha(group)
                    or set(continuation.get("books", {})) != set(HGB_STRATEGIES)):
                raise ValueError("PAPER_FIRST_CONTINUATION_GROUP_NOT_DURABLY_COMMITTED")
        elif any(engine._first_continuation_record("paper_first_continuation", group["books"][sid]) is not None
                 for sid, engine in self._active_engines().items()):
            raise ValueError("PAPER_FIRST_CONTINUATION_GROUP_NOT_DURABLY_COMMITTED")
        source_group = continuation or group
        if source_group.get("display_binding") is not None:
            from .best_broker import BestBroker
            deadline = timestamp(source_group["deadline_utc"])
            BestBroker._first_execution_display_binding(
                {sid: self.plans[sid] for sid in self._active_ids()}, self.plan_metadata, data, self.source,
                account_states={sid: self.close_states[sid] for sid in self._active_ids()},
                expected=source_group["display_binding"], allow_closed_display=clock >= deadline
                    and not any(engine._pending() for engine in self._active_engines().values()))
            full_refs = self.plan_metadata["source_refs"]
        else:
            full_refs = self._catchup_source_refs(data)
        ends = []
        for sid, engine in self._active_engines().items():
            permission = group["books"][sid]
            if (engine._get("paper_first_execution", None) != permission
                    or permission.get("display_binding") != group.get("display_binding")):
                raise ValueError("PAPER_FIRST_EXECUTION_PERMISSION_NOT_COMMITTED")
            if continuation is not None and engine._first_continuation_record("paper_first_continuation", permission) != continuation["books"][sid]:
                raise ValueError("PAPER_FIRST_CONTINUATION_PERMISSION_NOT_COMMITTED")
            batch_id = engine._paper_batch_id(sid, data["signal_date"], data["execution_date"])
            row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
            ends.append(engine._paper_first_execution_end(permission, strategy_id=sid, plan=self.plans[sid],
                batch=json.loads(row[0]) if row else None, batch_id=batch_id,
                metadata={**self.plan_metadata, "next_close_utc": data["next_close_utc"], "source_refs": full_refs},
                clock=clock, execution_window_seconds=self.execution_window_seconds))
        if not ends or any(end != ends[0] for end in ends):
            raise ValueError("PAPER_FIRST_EXECUTION_DEADLINES_CHANGED")
        return ends[0]

    def authorize_first_execution(self, *, execution_date, deadline_utc, authorization_id,
                                  expected_package_sha256, expected_plan_sha256_by_book, now, continuation=None):
        """Persist one reviewed first-attempt permit; never starts workers or creates batches."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        if continuation is not None:
            return self._authorize_first_continuation(execution_date=execution_date, deadline_utc=deadline_utc,
                authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                expected_plan_sha256_by_book=expected_plan_sha256_by_book, now=now, continuation=continuation)
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("PAPER_FIRST_EXECUTION_WAIT_FOR_TICK")
        try:
            with self.lock, ExitStack() as locks:
                self._pending_repair_guard()
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set() or not self.allow_partial_quotes
                        or set(self._active_ids()) != set(HGB_STRATEGIES)
                        or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600
                        or not isinstance(now, datetime) or now.tzinfo is None
                        or not isinstance(authorization_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", authorization_id)
                        or not isinstance(expected_plan_sha256_by_book, dict)
                        or set(expected_plan_sha256_by_book) != set(HGB_STRATEGIES)):
                    raise ValueError("PAPER_FIRST_EXECUTION_REQUIRES_STOPPED_ORIGINAL_HGB_BOOKS")
                clock, deadline = _now(now), timestamp(deadline_utc)
                data = self.source.status(now=clock)
                signal, execution, market_open = self._metadata(data, clock)
                from .best_broker import BestBroker
                display_binding = BestBroker._first_execution_display_binding(
                    {sid: self.plans[sid] for sid in self._active_ids()}, self.plan_metadata, data, self.source,
                    account_states={sid: self.close_states[sid] for sid in self._active_ids()})
                full_refs = self.plan_metadata["source_refs"] if display_binding is not None else self._catchup_source_refs(data)
                if (execution != execution_date or execution != clock.astimezone(NY).date().isoformat()
                        or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or data.get("data_gaps")
                        or any(data.get(k) != self.plan_metadata.get(k) for k in
                            ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                        or self.plan_metadata.get("execution_time_utc") != market_open.isoformat()
                        or not isinstance(expected_package_sha256, str)
                        or data.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                        or any(_first_execution_sha(self.plans.get(sid)) != expected_plan_sha256_by_book[sid]
                               for sid in HGB_STRATEGIES)
                        or any(self.meta.get(key, {}).get("signal_date") == signal for key in
                            ("paper_same_day_catchup", "paper_same_day_catchup_renewal"))
                        or self.meta.get("paper_reset", {}).get("request", {}).get("signal_date") == signal):
                    raise ValueError("PAPER_FIRST_EXECUTION_REVIEWED_PLAN_CHANGED")
                request = dict(execution_date=execution_date, deadline_utc=deadline.isoformat(),
                    authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                    expected_plan_sha256_by_book=expected_plan_sha256_by_book)
                prior = self.meta.get("paper_first_execution")
                if prior is not None and prior.get("signal_date") == signal:
                    if prior.get("request") != request:
                        raise ValueError("PAPER_FIRST_EXECUTION_ALREADY_AUTHORIZED_NO_RENEWAL")
                    self._first_execution_end(data, clock)
                    return prior
                group = dict(signal_date=signal, execution_date=execution, request=request,
                    authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(), books={})
                if display_binding is not None:
                    group["display_binding"] = display_binding
                for sid, engine in self._active_engines().items():
                    locks.enter_context(engine.lock)
                    engine._require_stopped()
                    batch_id = engine._paper_batch_id(sid, signal, execution)
                    if (engine._pending() or engine.halt_event.is_set()
                            or (engine._get("paper_first_execution", {}) or {}).get("signal_date") == signal
                            or engine.db.execute("SELECT 1 FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
                            or engine.db.execute("SELECT 1 FROM orders WHERE created_at>=? LIMIT 1", (market_open.isoformat(),)).fetchone()):
                        raise ValueError("PAPER_FIRST_EXECUTION_REQUIRES_UNSTARTED_BATCH")
                    permission = dict(reason="USER_REQUESTED_SAME_DAY_FIRST_EXECUTION", authorization_id=authorization_id,
                        signal_date=signal, execution_date=execution, strategy_id=sid, account_id=engine.paper_account_id,
                        batch_id=batch_id, source_plan_sha256=expected_plan_sha256_by_book[sid], source_refs=full_refs,
                        expected_package_sha256=full_refs["selected/package.json"]["sha256"], authorized_at_utc=clock.isoformat(),
                        deadline_utc=deadline.isoformat(), next_open_utc=data["next_open_utc"],
                        signal_close_utc=data["signal_close_utc"], next_close_utc=data["next_close_utc"],
                        execution_delay_minutes=0, execution_window_seconds=600,
                        pre_first_ledger_sha256=engine._paper_first_baseline(),
                        initial_required_codes=sorted({row["code"] for row in self.plans[sid]["rows"] if row["target_weight"]}
                            | {code for code, qty in engine._get("paper", {}).get("positions", {}).items() if qty}))
                    if display_binding is not None:
                        permission["display_binding"] = display_binding
                    engine._paper_first_execution_end(permission, strategy_id=sid, plan=self.plans[sid], batch=None,
                        batch_id=batch_id, metadata={**self.plan_metadata, "next_close_utc": data["next_close_utc"]},
                        clock=clock, execution_window_seconds=600)
                    group["books"][sid] = permission
                # A failure across independent DBs leaves no committed group and no automatic start.
                for sid, engine in self._active_engines().items():
                    engine._store_first_execution_permission("paper_first_execution", group["books"][sid])
                    engine._audit("PAPER_FIRST_EXECUTION_AUTHORIZED", _first_execution_sha(group["books"][sid]))
                previous_group = self.meta.get("paper_first_execution")
                try:
                    for item in ([previous_group] if previous_group is not None else []) + [group]:
                        slot = "paper_first_execution:" + item["signal_date"]
                        row = self.db.execute("SELECT value FROM settings WHERE key=?", (slot,)).fetchone()
                        if row and json.loads(row[0]) != item:
                            raise ValueError("PAPER_FIRST_EXECUTION_IMMUTABLE_GROUP_CHANGED")
                        self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)",
                            (slot, json.dumps(item, ensure_ascii=False, allow_nan=False)))
                    self.meta["paper_first_execution"] = group
                    self._persist()  # Commit the group slot and existing owner metadata in one DB transaction.
                except Exception:
                    self.db.rollback()
                    if previous_group is None:
                        self.meta.pop("paper_first_execution", None)
                    else:
                        self.meta["paper_first_execution"] = previous_group
                    raise
                self._event("PAPER_FIRST_EXECUTION_AUTHORIZED", group, clock)
                return group
        finally:
            self.tick_lock.release()

    def _authorize_first_continuation(self, *, execution_date, deadline_utc, authorization_id,
            expected_package_sha256, expected_plan_sha256_by_book, now, continuation):
        """Authorize one new explicit lease for the still-unstarted original HGB books."""
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("PAPER_FIRST_CONTINUATION_WAIT_FOR_TICK")
        started = time.monotonic()
        try:
            with self.lock, ExitStack() as locks:
                self._pending_repair_guard()
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set() or not self.allow_partial_quotes
                        or set(self._active_ids()) != set(HGB_STRATEGIES)
                        or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600
                        or not isinstance(now, datetime) or now.tzinfo is None
                        or not isinstance(continuation, dict)
                        or set(continuation) != {"expected_prior_sha256", "expected_ledger_sha256_by_book"}
                        or not isinstance(continuation.get("expected_ledger_sha256_by_book"), dict)
                        or set(continuation["expected_ledger_sha256_by_book"]) != set(HGB_STRATEGIES)
                        or not isinstance(expected_plan_sha256_by_book, dict)
                        or set(expected_plan_sha256_by_book) != set(HGB_STRATEGIES)):
                    raise ValueError("PAPER_FIRST_CONTINUATION_REQUIRES_STOPPED_ORIGINAL_BOOKS")
                clock, deadline = _now(now), timestamp(deadline_utc)
                data = self.source.status(now=clock)
                signal, execution, _ = self._metadata(data, clock)
                prior = self.meta.get("paper_first_execution")
                from .best_broker import BestBroker
                display = BestBroker._first_execution_display_binding(
                    {sid: self.plans[sid] for sid in self._active_ids()}, self.plan_metadata, data, self.source,
                    account_states={sid: self.close_states[sid] for sid in self._active_ids()})
                if display is None:
                    self._catchup_source_refs(data)
                request = dict(execution_date=execution_date, deadline_utc=deadline.isoformat(),
                    authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                    expected_plan_sha256_by_book=expected_plan_sha256_by_book, continuation=continuation)
                existing = self.meta.get("paper_first_continuation")
                if isinstance(existing, dict) and existing.get("signal_date") == signal:
                    if existing.get("request") != request:
                        raise ValueError("PAPER_FIRST_CONTINUATION_ALREADY_AUTHORIZED_NO_RENEWAL")
                    self._first_execution_end(data, clock)
                    return existing
                if (not isinstance(prior, dict) or prior.get("signal_date") != signal
                        or _first_execution_sha(prior) != continuation["expected_prior_sha256"]
                        or execution != execution_date or execution != clock.astimezone(NY).date().isoformat()
                        or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or data.get("data_gaps")
                        or any(data.get(k) != self.plan_metadata.get(k) for k in
                               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                        or data.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                        or any(_first_execution_sha(self.plans[sid]) != expected_plan_sha256_by_book[sid] for sid in HGB_STRATEGIES)
                        or any(self.meta.get(k, {}).get("signal_date") == signal for k in
                               ("paper_same_day_catchup", "paper_same_day_catchup_renewal"))
                        or self.meta.get("paper_reset", {}).get("request", {}).get("signal_date") == signal):
                    raise ValueError("PAPER_FIRST_CONTINUATION_REVIEWED_STATE_CHANGED")
                original_end = self._first_execution_end(data, clock)
                if original_end is None or clock < original_end:
                    raise ValueError("PAPER_FIRST_CONTINUATION_REQUIRES_EXPIRED_FIRST_PERMISSION")
                group = dict(signal_date=signal, execution_date=execution, request=request,
                    prior_group_sha256=_first_execution_sha(prior), authorized_at_utc=clock.isoformat(),
                    deadline_utc=deadline.isoformat(), books={})
                if display is not None:
                    group["display_binding"] = display
                for sid, engine in self._active_engines().items():
                    locks.enter_context(engine.lock)
                    engine._require_stopped()
                    if (engine.halt_event.is_set() or engine._pending()
                            or any(row[0] not in TERMINAL for row in engine.db.execute("SELECT status FROM orders"))
                            or engine._first_continuation_record("paper_first_continuation", prior["books"][sid]) is not None):
                        raise ValueError("PAPER_FIRST_CONTINUATION_PENDING_OR_ALREADY_AUTHORIZED")
                    engine._paper_first_no_attempt(self.plan_metadata)
                    baseline = engine._paper_first_baseline()
                    if baseline != continuation["expected_ledger_sha256_by_book"][sid]:
                        raise ValueError("PAPER_FIRST_CONTINUATION_LEDGER_CAS_CHANGED")
                    permission = dict(reason="USER_EXPLICIT_ONCE_SAME_DAY_FIRST_CONTINUATION",
                        authorization_id=authorization_id, signal_date=signal, execution_date=execution,
                        account_id=engine.paper_account_id, strategy_id=sid,
                        prior_permission_sha256=_first_execution_sha(prior["books"][sid]),
                        source_plan_sha256=expected_plan_sha256_by_book[sid],
                        authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(),
                        pre_first_ledger_sha256=baseline)
                    if display is not None:
                        permission["display_binding"] = display
                    _first_continuation_end(permission, prior["books"][sid], plan=self.plans[sid],
                        metadata={**self.plan_metadata, "next_close_utc": data["next_close_utc"]},
                        account_id=engine.paper_account_id, clock=clock, execution_delay_minutes=0, execution_window_seconds=600)
                    group["books"][sid] = permission
                if clock + timedelta(seconds=max(0, time.monotonic() - started)) >= deadline:
                    raise ValueError("PAPER_FIRST_CONTINUATION_EXPIRED_DURING_VALIDATION")
                for sid, engine in self._active_engines().items():
                    engine._store_first_execution_permission("paper_first_continuation", group["books"][sid])
                    engine._audit("PAPER_FIRST_CONTINUATION_AUTHORIZED", json.dumps(group["books"][sid], ensure_ascii=False))
                previous = self.meta.get("paper_first_continuation")
                try:
                    for item in ([previous] if previous is not None else []) + [group]:
                        slot = "paper_first_continuation:" + item["signal_date"]
                        row = self.db.execute("SELECT value FROM settings WHERE key=?", (slot,)).fetchone()
                        if row and json.loads(row[0]) != item:
                            raise ValueError("PAPER_FIRST_CONTINUATION_IMMUTABLE_GROUP_CHANGED")
                        self.db.execute("INSERT OR IGNORE INTO settings VALUES (?,?)", (slot, json.dumps(item, ensure_ascii=False, allow_nan=False)))
                    self.meta["paper_first_continuation"] = group
                    self._persist()
                except Exception:
                    self.db.rollback()
                    if previous is None:
                        self.meta.pop("paper_first_continuation", None)
                    else:
                        self.meta["paper_first_continuation"] = previous
                    raise
                self._event("PAPER_FIRST_CONTINUATION_AUTHORIZED", group, clock)
                return group
        finally:
            self.tick_lock.release()

    def authorize_catchup(self, *, execution_date, deadline_utc, now):
        """Authorize at most ten minutes of this day's original unfinished paper batch."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("PAPER_CATCHUP_WAIT_FOR_TICK")
        try:
            with self.lock:
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set() or not self.allow_partial_quotes):
                    raise ValueError("PAPER_CATCHUP_REQUIRES_STOPPED_UNLOCKED_WORKER")
                if not isinstance(now, datetime):
                    raise ValueError("PAPER_CATCHUP_REQUIRES_EXPLICIT_AWARE_NOW")
                clock, deadline = _now(now), timestamp(deadline_utc)
                data = self.source.status(now=clock)  # Metadata only; no refresh, inference or quotes.
                signal, execution, market_open = self._metadata(data, clock)
                full_refs = self._catchup_source_refs(data)
                opening = timestamp(self.plan_metadata["execution_time_utc"])
                original_end = opening + timedelta(seconds=self.execution_window_seconds)
                session_close = timestamp(data["next_close_utc"])
                if (execution != execution_date or clock.astimezone(NY).date().isoformat() != execution
                        or not market_open <= original_end <= clock < deadline <= min(clock + timedelta(seconds=600), session_close)
                        or deadline.astimezone(NY).date().isoformat() != execution
                        or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or data.get("data_gaps")
                        or not set(self._active_ids()).issubset(self.plans)
                        or any(data.get(key) != self.plan_metadata.get(key) for key in
                               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
                    raise ValueError("PAPER_CATCHUP_REQUIRES_ORIGINAL_SAME_DAY_BATCH")
                prior = self.meta.get("paper_same_day_catchup")
                if isinstance(prior, dict) and prior.get("signal_date") == signal:
                    if prior.get("execution_date") == execution and timestamp(prior["deadline_utc"]) == deadline:
                        self._catchup_end(data, clock)
                        return prior
                    raise ValueError("PAPER_CATCHUP_ALREADY_AUTHORIZED")
                record = dict(signal_date=signal, execution_date=execution,
                    authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(), books={})
                remaining = 0
                for sid, engine in self._active_engines().items():
                    engine._require_stopped()
                    if engine.halt_event.is_set():
                        raise ValueError("PAPER_CATCHUP_ACCOUNT_HALTED")
                    batch_id = engine._paper_batch_id(sid, signal, execution)
                    row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
                    batch = json.loads(row[0]) if row else {}
                    permission = dict(signal_date=signal, execution_date=execution, strategy_id=sid,
                        account_id=engine.paper_account_id, batch_id=batch_id,
                        source_plan_sha256=batch.get("source_plan_sha256"), source_refs=full_refs,
                        pretrade_equity=batch.get("pretrade_equity"), required_codes=batch.get("required_codes"),
                        processed_codes=batch.get("processed_codes", []),
                        authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(),
                        market_open_utc=market_open.isoformat(), next_close_utc=session_close.isoformat(),
                        execution_time_utc=opening.isoformat(), signal_close_utc=data["signal_close_utc"],
                        original_deadline_utc=original_end.isoformat(), reason="USER_REQUESTED_SAME_DAY_PAPER_CATCHUP")
                    engine._paper_catchup_end(permission, strategy_id=sid, plan=self.plans[sid], batch=batch,
                        batch_id=batch_id, opening=opening, closing=timestamp(data["signal_close_utc"]),
                        signal_date=signal, execution_date=execution, source_refs=full_refs, clock=clock,
                        original_end=original_end)
                    record["books"][sid] = permission
                    remaining += len(set(batch["required_codes"]) - set(batch["processed_codes"]))
                if not remaining:
                    raise ValueError("PAPER_CATCHUP_NO_REMAINING_TARGETS")
                # Validate every original book before persisting any permission; no batch/fill is changed here.
                for sid, engine in self._active_engines().items():
                    engine._set("paper_same_day_catchup", record["books"][sid])
                    engine._audit("PAPER_SAME_DAY_CATCHUP_AUTHORIZED", json.dumps(record["books"][sid], ensure_ascii=False))
                self.meta["paper_same_day_catchup"] = record
                self._persist()
                self._event("PAPER_SAME_DAY_CATCHUP_AUTHORIZED", record, clock)
                return record
        finally:
            self.tick_lock.release()

    def renew_catchup(self, *, execution_date, deadline_utc, expected_prior_sha256,
                      renewal_id, now, allowed_codes, single_sell_spread_bps=None):
        """One explicit renewal of expired KDK remainders; never replace the old permission."""
        if self.meta.get("strategy_membership_binding"):
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_FIVE_STRATEGY_MEMBERSHIP")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("PAPER_CATCHUP_RENEWAL_WAIT_FOR_TICK")
        try:
            with self.lock, ExitStack() as locks:
                if (self.closed or not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                        or self.halt_event.is_set() or not self.allow_partial_quotes
                        or set(self._active_ids()) != set(HGB_STRATEGIES)):
                    raise ValueError("PAPER_CATCHUP_RENEWAL_REQUIRES_STOPPED_HGB_WORKER")
                if (not isinstance(renewal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", renewal_id)
                        or allowed_codes != ["US.KDK"] or not isinstance(now, datetime)
                        or (single_sell_spread_bps is not None and
                            (type(single_sell_spread_bps) is not int or single_sell_spread_bps != 60))):
                    raise ValueError("PAPER_CATCHUP_RENEWAL_REQUEST_INVALID")
                started, clock, deadline = time.monotonic(), _now(now), timestamp(deadline_utc)
                original = self.meta.get("paper_same_day_catchup")
                if (not isinstance(original, dict) or not isinstance(expected_prior_sha256, str)
                        or hashlib.sha256(_bytes(original)).hexdigest() != expected_prior_sha256):
                    raise ValueError("PAPER_CATCHUP_RENEWAL_PRIOR_CHANGED")
                data = self.source.status(now=clock)  # Metadata only; never quote, load or refresh.
                signal, execution, market_open = self._metadata(data, clock)
                full_refs = self._catchup_source_refs(data)
                if (original.get("signal_date") != signal or original.get("execution_date") != execution
                        or set(original.get("books", {})) != set(self._active_ids())):
                    raise ValueError("PAPER_CATCHUP_RENEWAL_ORIGINAL_BINDING_INVALID")
                previous = self.meta.get("paper_same_day_catchup_renewal")
                if isinstance(previous, dict) and previous.get("signal_date") == signal:
                    if (previous.get("renewal_id") == renewal_id and previous.get("execution_date") == execution_date
                            and previous.get("deadline_utc") == deadline.isoformat()
                            and previous.get("expected_prior_sha256") == expected_prior_sha256
                            and previous.get("allowed_codes") == allowed_codes
                            and previous.get("single_sell_spread_bps") == single_sell_spread_bps):
                        self._catchup_end(data, clock)
                        return previous
                    raise ValueError("PAPER_CATCHUP_ALREADY_RENEWED")
                opening = timestamp(self.plan_metadata["execution_time_utc"])
                original_end = opening + timedelta(seconds=self.execution_window_seconds)
                session_close = timestamp(data["next_close_utc"])
                if (execution != execution_date or clock.astimezone(NY).date().isoformat() != execution
                        or not market_open <= original_end <= timestamp(original["deadline_utc"]) <= clock < deadline
                        or deadline > min(clock + timedelta(seconds=600), session_close)
                        or deadline.astimezone(NY).date().isoformat() != execution
                        or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or data.get("data_gaps")
                        or any(data.get(key) != self.plan_metadata.get(key) for key in
                               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
                    raise ValueError("PAPER_CATCHUP_RENEWAL_SAME_DAY_EXPIRED_PERMISSION_REQUIRED")
                record = dict(signal_date=signal, execution_date=execution, renewal_id=renewal_id,
                    expected_prior_sha256=expected_prior_sha256, allowed_codes=list(allowed_codes),
                    authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(), books={})
                if single_sell_spread_bps is not None:
                    record["single_sell_spread_bps"] = single_sell_spread_bps
                remaining, originals = 0, {}
                for sid, engine in self._active_engines().items():
                    locks.enter_context(engine.lock)
                    engine._require_stopped()
                    if (engine.halt_event.is_set() or engine._pending()
                            or any(row[0] not in TERMINAL for row in engine.db.execute("SELECT status FROM orders"))):
                        raise ValueError("PAPER_CATCHUP_RENEWAL_PENDING_OR_HALTED")
                    old = original["books"][sid]
                    if engine._get("paper_same_day_catchup", None) != old:
                        raise ValueError("PAPER_CATCHUP_RENEWAL_PRIOR_CHANGED")
                    previous_book = engine._get("paper_same_day_catchup_renewal", None)
                    if isinstance(previous_book, dict) and previous_book.get("signal_date") == signal:
                        raise ValueError("PAPER_CATCHUP_RENEWAL_INCOMPLETE_COMMIT")
                    batch_id = engine._paper_batch_id(sid, signal, execution)
                    row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
                    batch = json.loads(row[0]) if row else {}
                    engine._paper_catchup_end(old, strategy_id=sid, plan=self.plans[sid], batch=batch,
                        batch_id=batch_id, opening=opening, closing=timestamp(data["signal_close_utc"]),
                        signal_date=signal, execution_date=execution, source_refs=full_refs,
                        clock=clock, original_end=original_end)
                    pending = set(batch["required_codes"]) - set(batch["processed_codes"])
                    if not pending.issubset(allowed_codes):
                        raise ValueError("PAPER_CATCHUP_RENEWAL_REMAINDER_SCOPE_CHANGED")
                    remaining += len(pending)
                    permission = dict(old, reason="USER_REQUESTED_SAME_DAY_PAPER_CATCHUP_RENEWAL",
                        renewal_id=renewal_id, prior_permission_sha256=hashlib.sha256(_bytes(old)).hexdigest(),
                        authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(),
                        allowed_codes=list(allowed_codes), processed_codes=list(batch["processed_codes"]),
                        original_batch_sha256=hashlib.sha256(_bytes(batch)).hexdigest(),
                        prior_execution_decisions=deepcopy(batch.get("execution_decisions", [])))
                    if single_sell_spread_bps is not None:
                        held = engine._get("paper", {}).get("positions", {}).get("US.KDK", 0)
                        weight = next((row["target_weight"] for row in self.plans[sid]["rows"]
                                       if row["code"] == "US.KDK"), 0)
                        if pending != {"US.KDK"} or weight != 0 or type(held) is not int or held <= 0:
                            raise ValueError("PAPER_SINGLE_SELL_REQUIRES_ORIGINAL_ZERO_TARGET")
                        permission["single_sell_override"] = dict(code="US.KDK", side="SELL",
                            target_qty=0, max_qty=held, spread_bps=single_sell_spread_bps)
                    record["books"][sid] = permission
                    originals[sid] = engine.db.execute("SELECT value FROM settings WHERE key='paper_same_day_catchup_renewal'").fetchone()
                if not remaining:
                    raise ValueError("PAPER_CATCHUP_RENEWAL_NO_REMAINING_TARGETS")
                if clock + timedelta(seconds=time.monotonic() - started) >= deadline:
                    raise ValueError("PAPER_CATCHUP_RENEWAL_EXPIRED_DURING_VALIDATION")
                old_meta = deepcopy(self.meta)
                try:
                    for sid, engine in self._active_engines().items():
                        engine._set("paper_same_day_catchup_renewal", record["books"][sid])
                    self.meta["paper_same_day_catchup_renewal"] = record
                    self._persist()
                except Exception:
                    self.meta = old_meta
                    for sid, engine in self._active_engines().items():
                        if originals[sid] is None:
                            engine.db.execute("DELETE FROM settings WHERE key='paper_same_day_catchup_renewal'")
                        else:
                            engine.db.execute("INSERT OR REPLACE INTO settings VALUES ('paper_same_day_catchup_renewal',?)", originals[sid])
                        engine.db.commit()
                    self._persist()
                    raise
                for sid, engine in self._active_engines().items():
                    engine._audit("PAPER_CATCHUP_EXPLICIT_RENEWAL", json.dumps(dict(renewal_id=renewal_id,
                        prior_permission_sha256=record["books"][sid]["prior_permission_sha256"],
                        deadline_utc=record["deadline_utc"], allowed_codes=allowed_codes)))
                    if single_sell_spread_bps is not None:
                        engine._audit("PAPER_SINGLE_SELL_SPREAD_AUTHORIZED", json.dumps(dict(
                            permission_sha256=hashlib.sha256(_bytes(record["books"][sid])).hexdigest(),
                            scope=record["books"][sid]["single_sell_override"]), ensure_ascii=False))
                self._event("PAPER_CATCHUP_EXPLICIT_RENEWAL", record, clock)
                return record
        finally:
            self.tick_lock.release()

    def halt(self):
        self.halt_event.set()
        self.stop_event.set()
        self._maintenance_user_stop()
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
        self._cancel_execution_charts()  # Persist the original halt before chart cleanup can fail.
        return self.state()

    def _books_input(self):
        result = {}
        for sid, engine in self._active_engines().items():
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
        codes = {row["code"] for sid, plan in self.plans.items() if sid in self._active_ids() for row in plan.get("rows", []) if row["target_weight"]}
        for engine in self._active_engines().values():
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
        if self.manual_data_updates:
            return data
        if data.get("status") in {"READY", "OPEN_WINDOW"} and not data.get("data_gaps"):
            return data
        opening = self._scheduled_open(data["next_open_utc"])
        # A complete same-date signal needs no refresh while delayed execution waits.
        if (data.get("status") == "MISSED_OPEN" and not data.get("data_gaps")
                and data.get("source_date") and data["source_date"] == data.get("signal_date")
                and timestamp(data["next_open_utc"]) <= now < opening):
            return data
        close = timestamp(data["signal_close_utc"])
        session_close = timestamp(data["next_close_utc"])
        # Use the configured execution window; after close, the original updater
        # can prepare the next signal without reopening this signal's old trades.
        if opening + timedelta(seconds=self.execution_window_seconds) <= now < session_close:
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

    def _prepare(self, data, now, *, explicit_update=False):
        next_clock = self._next_ordinary_clock(data, now, explicit_update=explicit_update)
        signal = data["signal_date"]
        row = self.db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
        repair = json.loads(row[0]) if row else None
        if repair and repair.get("signal_date") == signal:
            from .applied_source import _reference, _json, _state
            self._pending_repair_guard()
            if (data.get("data_gaps") or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                    or any(data.get(key) != self.plan_metadata.get(key) for key in
                           ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
                raise ValueError("PENDING_REPAIR_PAPER_FROZEN_CLOCK_CHANGED")
            self._match_source_refs(self.plan_metadata.get("source_refs"), data, "PENDING_REPAIR_PAPER_SOURCE_CHANGED")
            archive = repair["paper_archive"]
            _reference(archive["path"], archive["sha256"])
            archived = _json(archive["path"])
            if (archived.get("plans") != {sid: self.plans.get(sid) for sid in HGB_STRATEGIES}
                    or archived.get("source_refs") != self.plan_metadata.get("source_refs")
                    or archived.get("states") != {sid: _state(self.close_states[sid], signal) for sid in HGB_STRATEGIES}):
                raise ValueError("PENDING_REPAIR_PAPER_FROZEN_ARCHIVE_CHANGED")
            return
        reset = self.meta.get("paper_reset")
        if reset and signal == reset["request"]["signal_date"]:
            expected_plans = self._initial_hgb_target_plans(reset)
            if (reset.get("phase") != "COMMITTED" or self.meta.get("plan_signal_date") != signal
                    or self.meta.get("plan_execution_date") != data["execution_date"] or data.get("data_gaps")
                    or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                    or any(data.get(key) != self.plan_metadata.get(key) for key in
                           ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                    or any(self.plans.get(sid) != expected_plans[sid]
                           or self.engines[sid]._get("paper_epoch_id", None) != reset["request"]["reset_id"]
                           for sid in self._active_ids())):
                raise ValueError("HGB_RESET_INITIAL_FROZEN_PLAN_CHANGED")
            self._reset_archive(reset)
            self._match_source_refs(self.plan_metadata.get("source_refs"), data, "HGB_RESET_INITIAL_SOURCE_CHANGED")
            return
        if self.manual_data_updates and not explicit_update:
            if self.plan_metadata.get("signal_date") == signal and all(sid in self.plans for sid in self._active_ids()):
                if any(self.plan_metadata.get(key) != data.get(key) for key in
                        ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
                    raise ValueError("FROZEN_BOOK_CLOCK_CHANGED")
                self._match_source_refs(self.plan_metadata.get("source_refs"), data, "FROZEN_BOOK_SOURCE_CHANGED")
                return
            self.meta.update(status="WAITING_MANUAL_UPDATE", reason="等待每日手动更新并准备当期目标；保留历史计划")
            return

        inputs = self._books_input()
        key = (signal, _fingerprint(inputs), _fingerprint(data.get("source_refs", {})))
        if key == self.loaded_key:
            return
        states = self.source.close_states(books=inputs, signal_date=signal)
        if not isinstance(states, dict) or set(states) != set(self._active_ids()):
            raise ValueError("SIGNAL_CLOSE_STATES_INCOMPLETE")
        for sid, state in states.items():
            if state.get("signal_date") != signal or state.get("valuation_basis") != "SIGNAL_CLOSE":
                raise ValueError("SIGNAL_CLOSE_STATE_CLOCK: " + sid)
            weights, cash = state.get("weights"), number(state.get("cash_weight"), "收盘现金权重")
            if not isinstance(weights, dict) or abs(sum(number(w, "收盘持仓权重") for w in weights.values()) + cash - 1) > 1e-8:
                raise ValueError("SIGNAL_CLOSE_STATE_WEIGHTS: " + sid)
            if "equity" in state:
                self.engines[sid].paper_record_close(signal, state)
        with _manual_inference_update(self, self.source) if explicit_update else nullcontext():
            loaded = self.source.load(states=states, now=now)
        self._metadata(loaded, now)
        if any(loaded.get(key) != data.get(key) for key in
               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
            raise ValueError("SOURCE_CHANGED_DURING_PLAN")
        plans = loaded.get("plans", {})
        if set(plans) != set(self._active_ids()):
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
            if next_clock and self._next_ordinary_clock(loaded, now, explicit_update=explicit_update) != next_clock:
                raise ValueError("DEFERRED_ORDINARY_CLOCK_REQUIRES_ACCEPTED_SOURCE")
            previous = (deepcopy(self.meta), deepcopy(self.plans), deepcopy(self.close_states),
                deepcopy(self.plan_metadata), deepcopy(self.book_status), self.loaded_key,
                self.execution_delay_minutes, self.execution_window_seconds) if next_clock else None
            try:
                event = self._activate_next_ordinary_clock(next_clock, loaded, now)
                self.plans.update(plans)
                self.close_states.update(states)
                self.loaded_key = key
                self.plan_metadata = {key: loaded.get(key) for key in ("signal_date", "execution_date",
                    "next_open_utc", "signal_close_utc", "source_refs", "source_date")}
                self.plan_metadata.update(execution_time_utc=self._scheduled_open(loaded["next_open_utc"]).isoformat(),
                                          execution_delay_minutes=self.execution_delay_minutes,
                                          execution_window_seconds=self.execution_window_seconds,
                                          allow_partial_quotes=self.allow_partial_quotes)
                self.meta.update(source_refs=loaded.get("source_refs", data.get("source_refs", {})),
                                 sourcecutoff=signal, plan_signal_date=signal, plan_execution_date=loaded["execution_date"])
                self._persist(event=event)  # Accepted plans and clock share one original-owner commit.
            except Exception:
                if previous is not None:
                    (self.meta, self.plans, self.close_states, self.plan_metadata, self.book_status, self.loaded_key,
                        self.execution_delay_minutes, self.execution_window_seconds) = previous
                raise
            error = self.meta.get("last_error", "")
            prefix = "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:"
            if (isinstance(error, str) and error.startswith(prefix)
                    and code_valid("US." + error[len(prefix):])
                    and not data.get("data_gaps") and not loaded.get("data_gaps")):
                # Only complete close/plan preparation proves this specific
                # source failure recovered. Quote/order errors stay untouched.
                self._event("SOURCE_PREPARATION_RECOVERED", {"previous_error": error,
                    "signal_date": signal, "execution_date": loaded["execution_date"]}, now)
                self.meta["last_error"] = ""
                self._persist()

    @staticmethod
    def _fresh_quotes(quotes, now):
        for code, quote in quotes.items():
            age = (now - timestamp(quote["asof"])).total_seconds()
            if not 0 <= age <= 30:
                raise ValueError("真实纸面标价过期或来自未来: " + code)

    def _market_summary(self):
        errors = self.meta.get("book_quote_errors", {})
        self.meta["connection_error"] = "; ".join(f"{sid}: {errors[sid]}" for sid in self._active_ids() if errors.get(sid))
        stamps = [stamp for sid, stamp in self.meta.get("book_quote_asof", {}).items() if sid in self._active_ids()]
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

    def _mark_current_books(self, *, now=None, record_cash=False, respect_stop=False, active_only=False):
        """Revalue held shares only; never prepare a signal, alter a plan or execute."""
        engines = self._active_engines() if active_only else self.engines
        held_by_book = {sid: sorted(row["code"] for row in engine.paper_book()["positions"] if row["qty"])
                        for sid, engine in engines.items()}
        codes = sorted({code for held in held_by_book.values() for code in held})
        if respect_stop and (self.stop_event.is_set() or self.halt_event.is_set()):
            return {}
        try:
            response = self.quote_feed.quotes_partial(codes, refresh=True) if codes else {"quotes": {}, "errors": {}}
            quotes, errors = dict(response["quotes"]), dict(response["errors"])
        except Exception as exc:
            quotes, errors = {}, {code: str(exc) for code in codes}
        clock = _now(now)
        reports = {}
        for sid, engine in engines.items():
            if respect_stop and (self.stop_event.is_set() or self.halt_event.is_set()):
                break
            clock = _now(now)  # Recheck source age after each independent book write.
            held = held_by_book[sid]
            if not held:
                if record_cash:
                    day = clock.astimezone(NY).date().isoformat()
                    with engine.lock:
                        if engine.db.execute("SELECT 1 FROM paper_nav WHERE day=?", (day,)).fetchone() is None:
                            engine.paper_mark({}, day=day, basis="CASH_LEDGER")
                continue
            valid, failures = {}, {}
            for code in held:
                try:
                    quote = quotes[code]
                    self._fresh_quotes({code: quote}, clock)
                    if (quote.get("tradable") is not True or quote.get("currency") != "USD"
                            or quote.get("market") != "US" or quote.get("source") != "MOOMOO_OPEND"):
                        raise ValueError("持仓估值拒绝非正常美股真实报价")
                    number(quote["price"], "真实标价", minimum=1e-12)
                    valid[code] = quote
                except Exception as exc:
                    failures[code] = str(errors.get(code) or ("没有合格的新报价" if code not in quotes else exc))
            try:
                with engine.lock:
                    book = engine.paper_mark(valid, day=clock.astimezone(NY).date().isoformat(),
                        observed_at_utc=clock.isoformat(), failed_quotes=failures)
                report = book["valuation"]
                reports[sid] = report
                with self.lock:
                    self.meta.setdefault("book_valuation", {})[sid] = report
                    gaps = [row["code"] + ": " + row["reason"] for row in report["failed_quotes"]]
                    if report["unmarked_codes"]:
                        gaps.append("缺少真实旧标价: " + ", ".join(report["unmarked_codes"]))
                    if gaps:
                        self.meta.setdefault("book_quote_errors", {})[sid] = "; ".join(gaps)
                    else:
                        self.meta.setdefault("book_quote_errors", {}).pop(sid, None)
                    if report["held_asof_min"]:
                        self.meta.setdefault("book_quote_asof", {})[sid] = report["held_asof_min"]
                    if report["fresh_held_count"]:
                        self.meta["quote_source"] = "MOOMOO_OPEND"
            except Exception as exc:
                with self.lock:
                    self.meta.setdefault("book_quote_errors", {})[sid] = str(exc)
                reports[sid] = dict(nav_recorded=False, error=str(exc))
        with self.lock:
            self._market_summary()
        return dict(valuation_only=True, observed_at_utc=clock.isoformat(), books=reports)

    def mark_current_books(self, now=None):
        """Explicit mark-only control, also permitted while a paper strategy is paused."""
        if self.closed:
            raise ValueError("执行器已关闭")
        if not self.tick_lock.acquire(blocking=False):
            raise ValueError("账户正在处理，请稍后刷新估值")
        try:
            # Source/trading/broker methods are deliberately absent from this path.
            result = self._mark_current_books(now=now)
            self._persist()
            return result
        finally:
            self.tick_lock.release()

    def _execution_charts_idle_after_windows(self, data, clock):
        """Maintenance may use the heavy owner only after every applicable window."""
        today = clock.astimezone(NY).date().isoformat()
        if data["execution_date"] == today:
            ends = [self._book_execution_window(sid, data, clock)[1] for sid in self._active_ids()]
            for candidate in (self._first_execution_end(data, clock), self._catchup_end(data, clock)):
                if candidate is not None:
                    ends.append(candidate)
        elif data["signal_date"] == today and timestamp(data["next_open_utc"]) > clock:
            ends = [timestamp(data["signal_close_utc"])]  # Conservatively covers all completed-session windows.
        else:
            return False
        for engine in self._active_engines().values():
            if engine.halt_event.is_set() or engine._pending():
                return False
        broker = self.best_broker
        if broker is not None:
            with broker.lock:
                if broker.engine.halt_event.is_set() or broker.engine._pending():
                    return False
                if data["execution_date"] == today:
                    ends.append(broker._scheduled_open(data["next_open_utc"]) + timedelta(seconds=broker.execution_window_seconds))
                if broker.plan and broker.metadata.get("execution_date") == today:
                    ends.append(broker._execution_end())
        return bool(ends) and clock >= max(ends)

    @staticmethod
    def _validate_main_charts_metadata(main, clock):
        if (not isinstance(main, dict) or main.get("status") not in {"READY", "PREFLIGHT", "BLOCKED"}
                or type(main.get("models_loaded")) is not int or main["models_loaded"] != 0
                or type(main.get("ledger_values_decoded")) is not int or main["ledger_values_decoded"] != 0
                or main.get("broker_action_allowed") is not False):
            raise ValueError("MAIN_CHART_METADATA_RESPONSE_INVALID")
        context = deepcopy(main.get("context", {}))
        if main["status"] in {"READY", "PREFLIGHT"}:
            if (not isinstance(context, dict) or main.get("end") != context.get("target_session")
                    or not isinstance(main.get("end"), str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", main["end"])):
                raise ValueError("MAIN_CHART_METADATA_CALENDAR_CHANGED")
            fields = ("driver_ref", "publication_ref", "capture_ref", "daily_report_ref") if main["status"] == "PREFLIGHT" else ("driver_ref", "publication_ref")
            if context.get('finite_ca_admission_ref') is not None:
                fields += ('finite_ca_admission_ref', 'original_driver_ref')
            for field in fields:
                identity = context.get(field)
                if (not isinstance(identity, dict) or not isinstance(identity.get("path"), str) or not identity["path"]
                        or not isinstance(identity.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])):
                    raise ValueError("MAIN_CHART_METADATA_IDENTITY_INVALID:" + field)
        if main["status"] == "PREFLIGHT":
            request = main.get("request", {})
            if (not isinstance(request, dict) or request.get("context") != context
                    or request.get("capture_ref") != context.get("capture_ref")
                    or request.get("finite_ca_admission_ref") != context.get("finite_ca_admission_ref")
                    or timestamp(request.get("as_of")) != clock):
                raise ValueError("MAIN_CHART_METADATA_REQUEST_CHANGED")
        return context

    def _execution_charts_tick(self, data, clock, *, explicit_update=False):
        """One owned queue, with independent original and fixed MAIN receipt stages."""
        job = getattr(self, "_execution_charts_job", None)
        probe = getattr(job,"quarantine_reason",None)
        quarantine = (probe() if callable(probe) else None)
        quarantine = quarantine if isinstance(quarantine,str) and quarantine else _worker_quarantine_reason()
        if isinstance(quarantine,str) and quarantine:
            if job is not None:
                try:
                    self._cancel_execution_charts()  # Propagate cancellation even to an already-running holder.
                except RuntimeError:
                    # The original cancel reports unverified/pending cleanup;
                    # keep the handle and resource isolation, never fake completion.
                    if not _worker_quarantine_reason() and not (callable(probe) and probe()):
                        raise
            previous = self.meta.get("execution_charts_update", {})
            self.meta["execution_charts_update"] = {**previous,"status":"QUARANTINED","error":quarantine}
            return
        starter = getattr(self.source, "start_execution_charts", None)
        reader = getattr(self.source, "execution_charts_status", None)
        if not callable(starter) or not callable(reader) or not isinstance(data, dict):
            if job is not None:
                self._cancel_execution_charts()
            return
        if self.manual_data_updates and not explicit_update and job is None:
            return
        main_reader = getattr(self.source, "main_execution_charts_status", None)
        main_ids = set(ACTIVE_PAPER_STRATEGY_IDS) - set(LEGACY_PAPER_STRATEGY_IDS)
        main_enabled = main_ids <= set(self._active_ids()) and callable(main_reader)
        ref = data.get("source_refs", {}).get("selected/package.json", {})
        key = {"signal_date": data.get("signal_date"), "execution_date": data.get("execution_date"),
               "package_sha256": ref.get("sha256")}
        previous = self.meta.get("execution_charts_update", {})
        try:
            today = clock.astimezone(NY).date().isoformat()
            eligible = (not self.closed and not self.stop_event.is_set() and not self.halt_event.is_set()
                and data.get("status") in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                and not data.get("data_gaps") and data.get("source_date") == key["signal_date"]
                and isinstance(key["package_sha256"], str) and re.fullmatch(r"[0-9a-f]{64}", key["package_sha256"])
                and (today == key["execution_date"] and clock >= timestamp(data["next_open_utc"])
                    or today == key["signal_date"] and clock >= timestamp(data["signal_close_utc"])
                    and clock < timestamp(data["next_open_utc"]))
                and self._execution_charts_idle_after_windows(data, clock))
        except (KeyError, TypeError, ValueError):
            eligible = False
        job = getattr(self, "_execution_charts_job", None)
        completed = False
        if job is not None:
            code = job.poll()
            if code is None:
                if (not eligible or any(previous.get("context", {}).get(field) != value for field, value in key.items())):
                    self._cancel_execution_charts()  # Retains the handle until owned cleanup finishes.
                return
            self._execution_charts_job = None
            completed = True
            outcome_reader = getattr(job, "result", None)
            outcome = outcome_reader() if callable(outcome_reader) else {}
            outcome = outcome if isinstance(outcome, dict) else {}
            main_result = outcome.get("stages", {}).get("main", {})
            attempted_main = previous.get("stages", {}).get("main", {}).get("status") == "PREFLIGHT"
            main_failure = main_result.get("exit_code", 0) != 0 or code != 0 and attempted_main and not main_result
            if main_enabled and main_failure and not main_result.get("resource_blocked") and not outcome.get("cancelled"):
                previous = {**previous, "failed_main_context": previous.get("context", {}).get("main"),
                    "failed_main_reason": main_result.get("reason", "MAIN_CHART_WORKER_NOT_VERIFIED_READY")}
            previous = {**previous, "status": "RETRY_WAIT", "error": "EXECUTION_CHART_WORKER_NOT_VERIFIED_READY:" + str(code),
                "next_retry_at_utc": (clock + timedelta(minutes=15)).isoformat()}
            self.meta["execution_charts_update"] = previous
        if not eligible or self.manual_data_updates and not explicit_update:
            return
        same_legacy = all(previous.get("context", {}).get(field) == value for field, value in key.items())
        if not completed and same_legacy and previous.get("next_retry_at_utc") and clock < timestamp(previous["next_retry_at_utc"]):
            return
        try:
            legacy = reader(key["execution_date"])
            legacy_ready = legacy.get("status") == "READY" and all(legacy.get(field) == value for field, value in key.items())
            legacy_mature = today == key["execution_date"] and clock >= timestamp(data["next_open_utc"])
            if not legacy_ready and not legacy_mature:
                # Match the original daily owner's WAITING_OPEN boundary; close
                # maintenance can extend MAIN but cannot replay a future opening.
                legacy = dict(status="WAITING_OPEN",signal_date=key["signal_date"],execution_date=key["execution_date"],
                    next_open_utc=data["next_open_utc"])
            main = main_reader(now=clock) if main_enabled else None
            if main_enabled:
                key["main"] = self._validate_main_charts_metadata(main, clock)
            main_ready = not main_enabled or main["status"] == "READY"
            stages = {"legacy": dict(legacy, status="READY" if legacy_ready else legacy.get("status", "UNAVAILABLE"))}
            if main_enabled:
                stages["main"] = {field: deepcopy(main[field]) for field in
                    ("status", "end", "reason", "manifest_ref", "source_qualification", "resource_blocked") if field in main}
            retained = {field: previous[field] for field in ("failed_main_context", "failed_main_reason") if field in previous}
            base = dict(context=key, stages=stages, **retained)
            if legacy_ready and main_ready:
                self.meta["execution_charts_update"] = {**base, "status": "READY", "error": "",
                    "completed_at_utc": clock.isoformat(), "action": "REUSED_OWNER_RECEIPT"}
                return
            main_failed = main_enabled and previous.get("failed_main_context") == key["main"]
            main_request = main.get("request") if main_enabled and main["status"] == "PREFLIGHT" and not main_failed else None
            if main_failed:
                stages["main"].update(status="BLOCKED", reason=previous.get("failed_main_reason", "MAIN_CHART_SAME_INPUT_REQUIRES_REPAIR"))
            legacy_needed = not legacy_ready and legacy_mature
            waiting_open = not legacy_ready and not legacy_mature and main_ready
            if completed or not legacy_needed and main_request is None:
                reason = stages.get("main", {}).get("reason", previous.get("error", "EXECUTION_CHART_WORKER_NOT_VERIFIED_READY"))
                self.meta["execution_charts_update"] = {**base, "status": "WAITING_OPEN" if waiting_open else "BLOCKED" if main_enabled else "RETRY_WAIT",
                    "error": "LEGACY_CHART_WAITING_OPEN" if waiting_open else reason, "next_retry_at_utc": (clock + timedelta(minutes=15)).isoformat()}
                return
            with self.lock:
                # stop/close cannot miss a job between creation and registration;
                # a newly granted manual window/pending order also has priority.
                if (self.closed or self._closing or self.stop_event.is_set() or self.halt_event.is_set()
                        or getattr(self, "_execution_charts_job", None) is not None
                        or not self._execution_charts_idle_after_windows(data, clock)):
                    return
                self._execution_charts_job = starter(legacy=legacy_needed, main_request=main_request) if main_enabled else starter()
                self.meta["execution_charts_update"] = {**base, "status": "RUNNING", "error": "",
                    "started_at_utc": clock.isoformat(), "action": "ISOLATED_ORIGINAL_CHART_WORKER"}
        except Exception as exc:
            self.meta["execution_charts_update"] = {"context": key, "status": "QUARANTINED" if _worker_quarantine_reason() else "RETRY_WAIT", "error": str(exc),
                "next_retry_at_utc": (clock + timedelta(minutes=15)).isoformat(),
                **{field: previous[field] for field in ("failed_main_context", "failed_main_reason") if field in previous}}

    def tick(self, now=None):
        if self._maintenance_active():
            return self.state()
        self._pending_repair_guard()
        clock = _now(now)
        if self.closed:
            raise ValueError("执行器已关闭")
        if not self.tick_lock.acquire(blocking=False):
            return self.state()
        data = None
        try:
            self._hook("tick", now=clock)
            data = self.source.status(now=clock)
            self._metadata(data, clock)
            data = self._refresh_if_due(data, clock)
            if (not self.meta.get("strategy_membership_binding") and not self.stop_event.is_set()
                    and not self.halt_event.is_set() and self._next_ordinary_clock(data, clock) is not None):
                self._prepare(data, clock)
            signal, execution, actual_opening = self._metadata(data, clock)
            opening = self._scheduled_open(data["next_open_utc"])
            if self.meta.get("strategy_membership_binding"):
                return self._tick_active_members(data, clock, supplied_now=now is not None)
            first_end = self._first_execution_end(data, clock)
            catchup_end = self._catchup_end(data, clock)
            auto_policy, auto_end = None, None
            if self.meta.get("automatic_completion_policy") is not None:
                candidate = self._current_automatic_completion_policy()
                policies = [engine._automatic_completion_policy(clock, sid, execution_date=execution)
                    for sid, engine in self._active_engines().items()]
                if policies and all(policy is not None for policy in policies):
                    if any(policy != candidate for policy in policies):
                        raise ValueError("PAPER_AUTOMATIC_COMPLETION_OWNER_POLICY_CHANGED")
                    if (data.get("data_gaps") or not self.allow_partial_quotes
                            or (not automatic_completion_clock_matches(candidate, self.execution_delay_minutes, self.execution_window_seconds)
                                if candidate.get("schema_version", 1) == 2 else
                                    self.execution_delay_minutes not in (0, 30) or self.execution_window_seconds != candidate["priority_window_seconds"])
                            or timestamp(data["next_close_utc"]).astimezone(NY).date().isoformat() != execution):
                        raise ValueError("PAPER_AUTOMATIC_COMPLETION_COHORT_POLICY_CHANGED")
                    auto_policy = candidate
                    auto_end = (opening + timedelta(seconds=candidate["priority_window_seconds"]) if candidate["schema_version"] == 2
                        else timestamp(data["next_close_utc"]) - timedelta(seconds=candidate["close_buffer_seconds"]))
            execution_end = auto_end or first_end or catchup_end or opening + timedelta(seconds=self.execution_window_seconds)
            with self.lock:
                self.meta.update({key: data.get(key) for key in ("signal_date", "execution_date",
                    "next_open_utc", "signal_close_utc", "next_close_utc", "upcoming_open_utc",
                    "next_refresh_utc", "refresh_not_before_utc", "source_refs", "data_gaps")})
                self.meta["sourcecutoff"] = signal
                upcoming = data.get("next_expected_open_utc") or data.get("upcoming_open_utc") or data["next_open_utc"]
                expected = opening if clock < execution_end else self._scheduled_open(upcoming)
                self.meta.update(execution_time_utc=opening.isoformat(), next_expected_execution_utc=expected.isoformat(),
                                  execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds)
            if self.stop_event.is_set() or self.halt_event.is_set():
                return self.state()
            if data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}:
                self.meta.update(status="WAITING_SOURCE", reason=data.get("reason", "当前信号未完成"))
                return self.state()
            # A reset's first signal always retains its exact accepted package, even after partial fills.
            if first_end is None and self.meta.get("paper_reset", {}).get("request", {}).get("signal_date") == signal:
                if not self._closed_reset_books(data, clock):
                    self._prepare(data, clock)
            # Once a signal has executed, its old close cannot revalue new holdings or rerun inference.
            executed = all(self._executed(sid, execution) for sid in self._active_ids())
            some_executed = any(self._processed(sid, execution) for sid in self._active_ids()) or (
                auto_policy is not None and any(self.book_status.get(sid, {}).get("execution_date") == execution
                    and self.book_status.get(sid, {}).get("executed_codes") for sid in self._active_ids()))
            auto_batches_exist = auto_policy is not None and any(engine.db.execute(
                "SELECT 1 FROM paper_batches WHERE id=?",
                (engine._paper_batch_id(sid, signal, execution),)).fetchone()
                for sid, engine in self._active_engines().items())
            if not executed and not some_executed and not auto_batches_exist and catchup_end is None and first_end is None:
                self._prepare(data, clock)
            elif not executed and auto_policy is not None:
                if (self.meta.get("plan_signal_date") != signal or self.meta.get("plan_execution_date") != execution
                        or data.get("data_gaps") or any(data.get(key) != self.plan_metadata.get(key)
                            for key in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
                    raise ValueError("PAPER_AUTOMATIC_COMPLETION_FROZEN_PLAN_CHANGED")
                self._match_source_refs(self.plan_metadata.get("source_refs"), data,
                    "PAPER_AUTOMATIC_COMPLETION_SOURCE_CHANGED")
            elif not executed and (self.meta.get("plan_signal_date") != signal or
                                   self.meta.get("plan_execution_date") != execution):
                raise ValueError("已成交部分账户，但该信号冻结计划未完整持久保存")
            if not executed:
                self._prewarm(data, clock, opening)
            if self.stop_event.is_set() or self.halt_event.is_set():
                return self.state()
            if self.manual_data_updates and (self.plan_metadata.get("signal_date") != signal
                    or any(sid not in self.plans for sid in self._active_ids())):
                self.meta.update(status="WAITING_MANUAL_UPDATE", reason="等待每日手动更新并准备当期目标；保留历史计划")
                return self.state()
            if clock >= execution_end and not executed:
                partial = self.allow_partial_quotes and some_executed
                self.meta.update(status="PARTIALLY_EXECUTED" if partial else "MISSED_OPEN",
                                 reason="本期窗口已结束；保留实际部分成交及未成交目标，不补发" if partial else "已错过该信号的计划执行窗口；不补发该信号")
                if (self.meta.get("last_missed_execution_date") != execution
                        or self.meta.get("last_missed_execution_time_utc") != opening.isoformat()):
                    self.meta.update(last_missed_execution_date=execution, last_missed_execution_time_utc=opening.isoformat())
                    self._event("MISSED_OPEN", dict(signal_date=signal, execution_date=execution,
                        next_open_utc=data["next_open_utc"], execution_time_utc=opening.isoformat(),
                        execution_delay_minutes=self.execution_delay_minutes), clock)
                for sid in self._active_ids():
                    if not self._executed(sid, execution):
                        previous = self.book_status.get(sid, {})
                        self.book_status[sid] = {**previous, "status": "PARTIALLY_EXECUTED" if self.allow_partial_quotes
                            and (self._processed(sid, execution) or (
                                auto_policy is not None and previous.get("executed_codes"))) else "MISSED_OPEN", "execution_date": execution,
                            "signal_date": signal, "reason": "本账户窗口已结束；保留实际成交和未成交原因，不补发"}
            elif clock < opening and not executed:
                self.meta.update(status="WAITING_OPEN", reason="已完成日信号就绪，等待计划执行时点 " + opening.isoformat())
            elif not executed:
                errors = {}
                for sid, engine in self._active_engines().items():
                    if self.stop_event.is_set() or self.halt_event.is_set():
                        break
                    if self._executed(sid, execution):
                        continue
                    stage = "QUOTES"
                    try:
                        book = engine.paper_book()
                        codes = {row["code"] for row in self.plans[sid]["rows"] if row["target_weight"]}
                        codes.update(row["code"] for row in book["positions"] if row["qty"])
                        if catchup_end is not None or auto_policy is not None:
                            batch_id = engine._paper_batch_id(sid, signal, execution)
                            row = engine.db.execute("SELECT payload FROM paper_batches WHERE id=?", (batch_id,)).fetchone()
                            if row is not None:
                                batch = json.loads(row[0])
                                codes = set(batch["required_codes"]) - set(batch["processed_codes"])
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
                        if auto_policy is not None:
                            options.update(automatic_completion_policy=auto_policy,
                                next_close_utc=data["next_close_utc"])
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
                        previous = self.book_status.get(sid, {})
                        if (previous.get("signal_date") != signal
                                or previous.get("execution_date") != execution):
                            previous = {}
                        self.book_status[sid] = dict(previous, status="BLOCKED", signal_date=signal,
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
                completed = [sid for sid in self._active_ids() if self._executed(sid, execution)]
                if len(completed) == len(self._active_ids()):
                    self.meta.update(status="EXECUTED", reason="三套独立账户已按计划窗口真实行情记入纸面成交",
                                     last_error=self.meta["connection_error"])
                else:
                    details = "; ".join(f"{sid}: {errors[sid]}" for sid in self._active_ids() if sid in errors)
                    partial = self.allow_partial_quotes and (
                        any(self._processed(sid, execution) for sid in self._active_ids()) or (
                            auto_policy is not None and any(self.book_status.get(sid, {}).get("executed_codes")
                                for sid in self._active_ids())))
                    self.meta.update(status="PARTIALLY_EXECUTED" if partial else "BLOCKED", last_error=details,
                        reason="已执行账户：" + (", ".join(completed) or "无") + "；受阻账户：" + details)
            else:
                self.meta.update(status="EXECUTED", reason="本信号已处理；等待下一完成日")
            # Mark held positions only during the source's actual regular session.
            if not self.manual_data_updates and (
                    not (opening <= clock < execution_end) or (auto_policy is not None and executed)):
                close = timestamp(data["next_close_utc"])
                if actual_opening <= clock < close:
                    self._mark_current_books(now=clock if now is not None else None,
                        record_cash=True, respect_stop=True)
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
                try:
                    self._execution_charts_tick(data, clock)
                except Exception as exc:
                    previous = self.meta.get("execution_charts_update", {})
                    job = getattr(self,"_execution_charts_job",None)
                    probe = getattr(job,"quarantine_reason",None)
                    quarantine = probe() if callable(probe) else None
                    quarantine = quarantine if isinstance(quarantine,str) and quarantine else _worker_quarantine_reason()
                    self.meta["execution_charts_update"] = {**previous, "status": "QUARANTINED" if isinstance(quarantine,str) and quarantine else "RETRY_WAIT", "error": str(exc),
                        "next_retry_at_utc": (clock + timedelta(minutes=15)).isoformat()}
                self._persist()
            self.tick_lock.release()

    def _poll_delay(self, now=None):
        clock = _now(now)
        opening = self.meta.get("execution_time_utc")
        if opening:
            seconds = (timestamp(opening) - clock).total_seconds()
            if 0 < seconds <= 30:
                return max(.05, min(1.0, seconds))
            record = self.meta.get("paper_first_execution", {})
            if record.get("signal_date") != self.meta.get("signal_date"):
                record = self.meta.get("paper_same_day_catchup_renewal", {})
            if record.get("signal_date") != self.meta.get("signal_date"):
                record = self.meta.get("paper_same_day_catchup", {})
            end = (timestamp(record["deadline_utc"]) if record.get("deadline_utc") and record.get("signal_date") == self.meta.get("signal_date")
                   and record.get("execution_date") == self.meta.get("execution_date")
                   else timestamp(opening) + timedelta(seconds=self.execution_window_seconds))
            if timestamp(opening) <= clock < end:
                return 1.0
        return 30.0

    def _run(self):
        try:
            while not self.stop_event.is_set():
                self.tick()
                if self.stop_event.wait(self._poll_delay()):
                    break
        finally:
            self._cancel_execution_charts()

    def trades(self):
        return sorted((trade for engine in self.engines.values() for trade in engine.paper_trades()),
                      key=lambda r: (r["filled_at"], r["strategy_id"], r["sequence"]))

    def state(self, *, compact=False):
        with self.lock:
            result = {**self.meta, "manual_data_updates": self.manual_data_updates, "running": not self.stop_event.is_set(),
                      "halted": self.halt_event.is_set(), "books": {}}
            if "automatic_completion_policy" in result:
                result["automatic_completion_policy"] = {k: v for k, v in
                    result["automatic_completion_policy"].items() if k != "broker_account_id"}
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
                result["books"][sid] = {**book, "strategy_id": sid, "name": APPLIED_STRATEGY_NAMES[sid],
                    "plan": plan, "planned_actions": actions, "status": self.book_status.get(sid, {}).get("status", result["status"]),
                    "execution": self.book_status.get(sid), "trades": engine.paper_trades(limit=100, compact=compact),
                    "nav_history": engine.paper_nav_history(limit=1000, compact=compact), "fee_bps": FEE_BPS,
                    "plan_metadata": self.meta.get("book_plan_metadata", {}).get(sid, self.plan_metadata), "close_state": self.close_states.get(sid),
                    "connection_error": self.meta.get("book_quote_errors", {}).get(sid, ""),
                    "quote_asof": self.meta.get("book_quote_asof", {}).get(sid),
                    "valuation": self.meta.get("book_valuation", {}).get(sid),
                    "reason": self.book_status.get(sid, {}).get("reason") or self.meta.get("book_quote_errors", {}).get(sid, "")}
                if sid not in self._active_ids():
                    result["books"][sid].update(status="PAUSED", reason="用户已暂停本策略；保留原账本与历史成交",
                        paused=True, plan_metadata=self.meta.get("inactive_plan_metadata", {}).get(sid))
                elif result["books"][sid]["status"] in {"EXECUTED", "PARTIALLY_EXECUTED"}:
                    projected = result["books"][sid]
                    frozen = projected["plan_metadata"]
                    batch = projected["execution"] or {}
                    # A restored batch describes its actual execution period; it
                    # cannot certify a later frozen target after a paused restart.
                    plan_clock = (frozen.get("signal_date"), frozen.get("execution_date")) if isinstance(frozen, dict) else (None, None)
                    bound_plan = bool(plan and all(isinstance(value, str) for value in plan_clock)
                        and plan.get("signal_date", plan_clock[0]) == plan_clock[0]
                        and plan.get("execution_date", plan_clock[1]) == plan_clock[1])
                    if not bound_plan or (batch.get("signal_date"), batch.get("execution_date")) != plan_clock:
                        current_plan = bound_plan and plan_clock == (self.meta.get("signal_date"), self.meta.get("execution_date"))
                        projected.update(status="TARGET_ONLY" if current_plan else "WAITING_SOURCE",
                            reason="当期冻结目标尚未执行；历史成交保留在原执行批次" if current_plan
                            else "执行批次与冻结计划日期不一致，待核验")
                elif result["status"] == "WAITING_OPEN" and not self._executed(sid, self.meta.get("execution_date")):
                    projected = result["books"][sid]
                    frozen = projected["plan_metadata"]
                    current_plan = bool(plan and isinstance(frozen, dict)
                        and frozen.get("signal_date") == self.meta.get("signal_date")
                        and frozen.get("execution_date") == self.meta.get("execution_date")
                        and plan.get("signal_date", frozen.get("signal_date")) == self.meta.get("signal_date"))
                    if projected["status"] in {"BLOCKED", "WAITING_MANUAL_UPDATE"}:
                        continue
                    if current_plan:
                        projected.update(status="WAITING_OPEN", reason=result["reason"])
                    else:
                        projected.update(status="BLOCKED", reason=projected["reason"]
                            or result.get("last_error") or "当期冻结计划尚未就绪")
            result["trades"] = sorted((trade for book in result["books"].values() for trade in book["trades"]),
                key=lambda r: (r["filled_at"], r["strategy_id"], r["sequence"]))[-100:]
            if result.get("strategy_membership_binding"):
                result["strategy_membership_binding"] = {k: v for k, v in result["strategy_membership_binding"].items()
                    if k != "preserved_cohort_setting"}
            result["membership_precondition_sha256"] = self._membership_precondition()
            result["roster_precondition_sha256"] = self._roster_precondition()
            result.update(accepted_roster_projection(self.meta))
            result["strategies"] = [dict(strategy_id=sid, name=APPLIED_STRATEGY_NAMES[sid], active=True) for sid in self._active_ids()]
            if self.meta.get("strategy_membership_binding") or self.meta.get("showcase_roster_binding"):
                inactive = {sid: book for sid, book in result["books"].items() if sid not in self._active_ids()}
                result["legacy_history"] = {"books": inactive}
                for sid in self._active_ids():
                    if sid not in result["books"]:
                        result["books"][sid] = dict(strategy_id=sid, name=APPLIED_STRATEGY_NAMES[sid],
                            account_id="paper-"+sid, mode="paper", paper=True, status="BLOCKED",
                            reason="SHOWCASE_ROSTER_BOOK_OWNER_OPEN_REQUIRED", book_owner_ready=False,
                            cash=None, equity=None, positions=[], trades=[], nav_history=[], trade_count=0,
                            inception_utc=self._roster_book_inception(sid))
                result["books"] = {sid: result["books"][sid] for sid in self._active_ids()}
            # Never wait for the SIM's source preparation while holding the PAPER
            # owner lock. Freeze this display copy before reading the other owner.
            if compact:
                from .server import applied_display_view
                result = applied_display_view(result)
            result = json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))
        if self.best_broker is not None:
            try:
                broker = self.best_broker.state()
            except Exception as exc:
                broker = dict(status="ERROR", last_error=str(exc))
            if compact:
                broker = applied_display_view({"broker": broker})["broker"]
            result["broker"] = broker
        return json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False))

    def display_state(self, *, lock_timeout_seconds=.1):
        """Read the existing owners with a single finite lock admission budget."""
        deadline = time.monotonic() + lock_timeout_seconds
        with ExitStack() as held:
            locks = [self.lock, *(engine.lock for engine in self.engines.values())]
            if self.best_broker is not None:
                locks += [self.best_broker.lock, self.best_broker.engine.lock]
            seen = set()
            for lock in locks:
                if id(lock) in seen:
                    continue
                seen.add(id(lock))
                if not lock.acquire(timeout=max(0., deadline - time.monotonic())):
                    raise TimeoutError("APPLIED_DISPLAY_OWNER_BUSY")
                held.callback(lock.release)
            return self.state(compact=True)

    def close(self):
        with self.lock:
            if self.closed:
                return
            self._closing = True  # No new owner may start during stop/join/book close.
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
