"""A dedicated HGB diagonal strategy budget in the selected US SIMULATE account.

The research close timestamp remains in the archived source plan. The execution
manifest is created inside its next-open window, after funds and quotes checks.
No source refresh, training, REAL orders or trading unlock is implemented here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from copy import deepcopy
from contextlib import closing, nullcontext
from decimal import Decimal, ROUND_CEILING
import json
import hashlib
import math
import re
import sqlite3
from pathlib import Path
import threading
import time
from zoneinfo import ZoneInfo

from .core import Engine, TERMINAL, _first_execution_sha, _first_execution_end, _first_continuation_end, _validate_first_continuation_state
from .brokers import BrokerError, BrokerOrderNotSent, BrokerReadError
from .strategy import (timestamp, now_iso, code_valid, number, auto_completion_spread_is_valid,
    ACTIVE_PAPER_STRATEGY_IDS, LEGACY_PAPER_STRATEGY_IDS, APPLIED_STRATEGY_NAMES, exact_hold_units, requested_gross_input, accepted_requested_gross_state, automatic_completion_clock_matches)

SID = "HGB_DIAG_5"
REPRICE_INTERVAL_SECONDS = 30
MAX_REPRICES_PER_ORDER = 10
TERMINAL_RETRY_COOLDOWN_SECONDS = 30
MAX_TERMINAL_RETRIES_PER_CODE = 5
MARKET_BUY_CASH_BUFFER = 1.03


class BestBroker:
    def __init__(self, runtime_root, source, budget=10000, *, engine=None, now=None,
                 execution_delay_minutes=None, execution_window_seconds=None, allow_partial_quotes=None, strategy_id=None, manual_data_updates=False):
        if execution_window_seconds is not None and (
                type(execution_window_seconds) is not int or not 1 <= execution_window_seconds <= 3600):
            raise ValueError("模拟执行窗口必须是1至3600的整数秒")
        if allow_partial_quotes is not None and type(allow_partial_quotes) is not bool:
            raise ValueError("模拟逐票执行必须是明确布尔值")
        if type(manual_data_updates) is not bool:
            raise ValueError("MANUAL_DATA_UPDATES_MODE_INVALID")
        self.manual_data_updates = manual_data_updates
        self.engine = engine or Engine(Path(runtime_root))
        self.source = source
        saved_strategy = self.engine._get("best_strategy_id", SID)
        if (saved_strategy not in ACTIVE_PAPER_STRATEGY_IDS
                or strategy_id is not None and strategy_id != saved_strategy):
            raise ValueError("SIM_STRATEGY_REQUIRES_EXPLICIT_BINDING")
        self.strategy_id = saved_strategy
        self.budget = float(budget)
        binding = self.engine._get("best_strategy_binding", None)
        if binding is not None:
            self._validate_strategy_binding(binding)
        elif self.strategy_id != SID:
            raise ValueError("SIM_STRATEGY_BINDING_REQUIRED")
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
        self._source_validation_pending = False
        self._source_retry_at = 0.0
        self.published_target_provider = None
        self.engine.published_target_manual_validator = self._manual_manifest_guard
        self.engine.native_first_execution_validator = self._native_first_manifest_guard
        self._closed_current_signal = False
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
        # A requested ordinary clock never rewrites the current signal's grant.
        if ((delay, window) == (25, 1500) and (saved_delay, saved_window) != (delay, window)
                and (signal := self._ordinary_clock_signal_to_preserve()) is not None):
            pending = dict(after_signal_date=signal, previous_delay_minutes=saved_delay,
                previous_window_seconds=saved_window, execution_delay_minutes=25, execution_window_seconds=1500)
            if self.engine._get("best_next_ordinary_execution_clock", None) != pending:
                with self.engine.db:
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                        ("best_next_ordinary_execution_clock", json.dumps(pending, sort_keys=True)))
                    self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (self._now().isoformat(),
                        "ORDINARY_EXECUTION_CLOCK_DEFERRED", json.dumps(pending, sort_keys=True)))
            delay, window = saved_delay, saved_window
            self.execution_window_seconds = window
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

    def _ordinary_clock_signal_to_preserve(self):
        saved = self.engine._get("best_plan", {}).get("metadata", {})
        signal = saved.get("signal_date")
        if not signal:
            return None
        execution = self.engine._get("best_execution", {})
        manual = self.engine._get("best_published_target_manual_completion", {}) or {}
        future = saved.get("execution_date", "") > self._now().astimezone(ZoneInfo("America/New_York")).date().isoformat()
        if (not future or execution.get("signal_date") == signal
                or manual.get("signal_date") == signal or self.engine._pending()):
            return signal
        return None

    def _next_ordinary_clock(self, signal):
        record = self.engine._get("best_next_ordinary_execution_clock", None)
        if record is None:
            return None
        expected = {"after_signal_date", "previous_delay_minutes", "previous_window_seconds",
            "execution_delay_minutes", "execution_window_seconds"}
        if (not isinstance(record, dict) or set(record) != expected
                or (record["execution_delay_minutes"], record["execution_window_seconds"]) != (25, 1500)
                or any(type(record[k]) is not int for k in expected - {"after_signal_date"})
                or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(record["after_signal_date"]))
                or (self.execution_delay_minutes, self.execution_window_seconds) !=
                    (record["previous_delay_minutes"], record["previous_window_seconds"])):
            raise ValueError("DEFERRED_ORDINARY_CLOCK_CHANGED")
        if signal <= record["after_signal_date"]:
            return None
        if self.engine._pending():
            raise ValueError("DEFERRED_ORDINARY_CLOCK_REQUIRES_RECONCILED_ACCOUNT")
        if not any(json.loads(row[0]) == record for row in self.engine.db.execute(
                "SELECT detail FROM audit WHERE event='ORDINARY_EXECUTION_CLOCK_DEFERRED'")):
            raise ValueError("DEFERRED_ORDINARY_CLOCK_AUDIT_CHANGED")
        return record

    def _require_legacy_strategy(self):
        if self.strategy_id != SID or self.engine._get("best_strategy_binding", None) is not None:
            raise ValueError("LEGACY_PERMISSION_NOT_TRANSFERABLE_TO_BOUND_STRATEGY")

    @staticmethod
    def _native_reset_binding(record):
        return dict(schema_version=2, binding_type="NATIVE_SIM_RESET_ADOPTION_R1",
            native_reset_id=record["reset_id"], native_reset_record_sha256=BestBroker._content_sha(record),
            account_id=record["new_account_id"], budget=record["budget"],
            previous_strategy_id=record["previous_strategy_id"], target_strategy_id=record["target_strategy_id"])

    def _validate_strategy_binding(self, binding):
        if binding.get("binding_type") == "NATIVE_SIM_RESET_ADOPTION_R1":
            record = self._native_reset_record()
            if binding != self._native_reset_binding(record) or binding["target_strategy_id"] != self.strategy_id:
                raise ValueError("NATIVE_RESET_STRATEGY_BINDING_CHANGED")
            self._native_reset_bootstrap_record(record)
            return
        audit = self.engine.db.execute("SELECT detail FROM audit WHERE event='SIM_STRATEGY_BOUND'")
        if (binding.get("target_strategy_id") != self.strategy_id
                or binding.get("account_id") != self.engine._get("best_account", None)
                or binding.get("budget") != self.budget
                or self._content_sha(binding.get("preserved_settings")) != binding.get("preserved_settings_sha256")
                or not any(json.loads(row[0]) == binding for row in audit)):
            raise ValueError("SIM_STRATEGY_BINDING_AUDIT_CHANGED")

    def _native_reset_manifest(self, namespace=None):
        prefix = namespace or ""
        where,params = ("substr(key,1,?)=?",(len(prefix),prefix)) if namespace else (
            "substr(key,1,?)!=? AND substr(key,1,?)!=?",(len("native_reset_archive/"),"native_reset_archive/",
                len("native_reset_receipt/"),"native_reset_receipt/"))
        keys = [row[0] for row in self.engine.db.execute("SELECT CASE WHEN typeof(key)='text' "
            "AND length(CAST(key AS BLOB))<=? THEN key ELSE NULL END FROM settings WHERE "+where+
            " ORDER BY key LIMIT 513",(len(prefix)+256,*params))]
        if len(keys) > 512:
            raise ValueError("NATIVE_RESET_ARCHIVE_ENTRY_LIMIT")
        manifest, total = {}, 0
        for stored_key in keys:
            if not isinstance(stored_key,str):
                raise ValueError("NATIVE_RESET_ARCHIVE_KEY_INVALID")
            key = stored_key[len(prefix):]
            if (not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}",key) or ".." in key
                    or key.startswith(("native_reset_archive/", "native_reset_receipt/"))):
                raise ValueError("NATIVE_RESET_ARCHIVE_KEY_INVALID")
            row = self.engine.db.execute("SELECT value FROM settings WHERE key=? AND typeof(value)='text' "
                "AND length(CAST(value AS BLOB)) BETWEEN 1 AND ?",
                (stored_key,min(16*1024*1024,64*1024*1024-total))).fetchone()
            if row is None:
                raise ValueError("NATIVE_RESET_RAW_UTF8_OR_SIZE_LIMIT")
            data = row[0].encode("utf-8");total += len(data)
            if len(data) > 16*1024*1024 or total > 64*1024*1024:
                raise ValueError("NATIVE_RESET_ARCHIVE_SIZE_LIMIT")
            manifest[key] = dict(archive_key=(prefix+key) if namespace else key,
                sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data))
        return manifest

    def _native_reset_table_prefix(self, table, last_rowid=None):
        if table not in {"orders", "order_fills", "audit"}:
            raise ValueError("NATIVE_RESET_HISTORY_TABLE_INVALID")
        if last_rowid is None:
            last_rowid = self.engine.db.execute("SELECT COALESCE(MAX(rowid),0) FROM "+table).fetchone()[0]
        if type(last_rowid) is not int or last_rowid < 0:
            raise ValueError("NATIVE_RESET_HISTORY_BOUND_INVALID")
        digest, count = hashlib.sha256(), 0
        for row in self.engine.db.execute("SELECT rowid,* FROM "+table+" WHERE rowid<=? ORDER BY rowid", (last_rowid,)):
            digest.update(json.dumps(list(row),ensure_ascii=False,sort_keys=True,
                separators=(",", ":"),allow_nan=False).encode("utf-8"));digest.update(b"\n");count += 1
        return dict(last_rowid=last_rowid, count=count, sha256=digest.hexdigest())

    def _native_reset_record(self):
        row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_native_reset_epoch' AND typeof(value)='text' AND length(CAST(value AS BLOB)) BETWEEN 1 AND 1048576").fetchone()
        if row is None or not isinstance(row[0], str) or len(row[0].encode("utf-8")) > 1024*1024:
            raise ValueError("NATIVE_RESET_EPOCH_RECEIPT_REQUIRED")
        raw, record = row[0], json.loads(row[0])
        fields = {"schema","reset_id","request","adopted_at_utc","old_account_id","new_account_id",
            "budget","previous_strategy_id","target_strategy_id","archive_namespace","archive_manifest",
            "archive_manifest_sha256","ledger_prefix","ledger_prefix_sha256","native_snapshot",
            "native_snapshot_sha256","eligible_accounts","old_pending_repair_sha256","initial_capital","initial_capital_sha256"}
        if (not isinstance(record, dict) or set(record) != fields or record.get("schema") != "NATIVE_SIM_RESET_ADOPTION_R1"
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(record.get("reset_id", "")))
                or raw != json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)):
            raise ValueError("NATIVE_RESET_EPOCH_RECEIPT_INVALID")
        request = record["request"]
        if (not isinstance(request,dict) or set(request) != {"reset_id","requested_at","expected_old_account_id",
                    "new_account_id","target_strategy_id","expected_precondition_sha256","budget"}
                or any(request[k] != record[k] for k in ("reset_id","new_account_id","target_strategy_id","budget"))
                or request["expected_old_account_id"] != record["old_account_id"]
                or any(not isinstance(record[k],str) or not re.fullmatch(r"[1-9][0-9]{0,19}",record[k])
                       for k in ("old_account_id","new_account_id"))
                or record["previous_strategy_id"] not in ACTIVE_PAPER_STRATEGY_IDS
                or type(record["budget"]) not in (int,float) or not math.isfinite(record["budget"]) or record["budget"] <= 0
                or type(request["budget"]) not in (int,float)
                or not isinstance(request["expected_precondition_sha256"],str)
                or not re.fullmatch(r"[0-9a-f]{64}",request["expected_precondition_sha256"])
                or timestamp(request["requested_at"]) > timestamp(record["adopted_at_utc"])):
            raise ValueError("NATIVE_RESET_REQUEST_BINDING_CHANGED")
        reset_id = record["reset_id"]
        saved = self.engine.db.execute("SELECT value FROM settings WHERE key=? AND typeof(value)='text' "
            "AND length(CAST(value AS BLOB)) BETWEEN 1 AND 1048576", ("native_reset_receipt/"+reset_id,)).fetchone()
        if (saved is None or saved[0] != raw or self.engine.db.execute(
                "SELECT COUNT(*) FROM audit WHERE event='NATIVE_SIM_RESET_ADOPTED' AND detail=?", (raw,)).fetchone()[0] != 1
                or record.get("archive_namespace") != "native_reset_archive/"+reset_id+"/"
                or record.get("old_account_id") == record.get("new_account_id")
                or record.get("target_strategy_id") not in ACTIVE_PAPER_STRATEGY_IDS
                or record.get("budget") != self.budget
                or self.engine._get("best_account", None) != record.get("new_account_id")
                or record.get("initial_capital_sha256") != self._content_sha(record.get("initial_capital"))
                or self.engine._get("best_capital", None) != record.get("initial_capital")):
            raise ValueError("NATIVE_RESET_EPOCH_BINDING_CHANGED")
        manifest = self._native_reset_manifest(record["archive_namespace"])
        if (manifest != record.get("archive_manifest")
                or self._content_sha(manifest) != record.get("archive_manifest_sha256")):
            raise ValueError("NATIVE_RESET_ARCHIVED_SETTINGS_CHANGED")
        initial = record["initial_capital"]
        native = record.get("native_snapshot", {})
        if (set(initial) != {"budget","account_id","unused_cash","initial_account_equity","started_at"}
                or initial["account_id"] != record["new_account_id"] or initial["budget"] != record["budget"]
                or initial["unused_cash"] != 0 or initial["initial_account_equity"] != record["budget"]
                or set(native) != {"cash","equity","positions","open_orders","quotes","funds_only","observed_at_utc"}
                or native.get("cash") != record["budget"] or native.get("equity") != record["budget"]
                or native.get("positions") != {} or native.get("open_orders") != [] or native.get("quotes") != {}
                or native.get("funds_only") is not True or self._content_sha(native) != record.get("native_snapshot_sha256")
                or record.get("eligible_accounts") != [dict(account_id=record["new_account_id"], market="US", environment="SIMULATE")]):
            raise ValueError("NATIVE_RESET_NATIVE_PROOF_CHANGED")
        if (timestamp(native["observed_at_utc"]) > timestamp(record["adopted_at_utc"])
                or initial["started_at"] != record["adopted_at_utc"]):
            raise ValueError("NATIVE_RESET_OBSERVATION_CLOCK_CHANGED")
        pending = manifest.get("pending_plan_repair")
        if record.get("old_pending_repair_sha256") != (pending["sha256"] if pending else None):
            raise ValueError("NATIVE_RESET_REPAIR_ARCHIVE_CHANGED")
        prefix = record.get("ledger_prefix", {})
        if set(prefix) != {"orders", "order_fills", "audit"} or self._content_sha(prefix) != record.get("ledger_prefix_sha256"):
            raise ValueError("NATIVE_RESET_HISTORY_PREFIX_INVALID")
        for table, expected in prefix.items():
            if self._native_reset_table_prefix(table,expected.get("last_rowid")) != expected:
                raise ValueError("NATIVE_RESET_HISTORY_PREFIX_CHANGED")
        return record

    def _native_reset_require_idle(self, owner):
        if owner is None or getattr(owner,"best_broker",None) is not self:
            raise ValueError("NATIVE_RESET_CANONICAL_COHORT_OWNER_REQUIRED")
        self.engine._require_stopped()
        if (not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                or self.engine._pending() or self.engine.halt_event.is_set()
                or getattr(self,"_manual_inference_quarantine_lock",None) is not None):
            raise ValueError("NATIVE_RESET_REQUIRES_PAUSED_TERMINAL_ORDERS")
        if owner is not None and (not owner.stop_event.is_set() or owner.halt_event.is_set()
                or owner.worker and owner.worker.is_alive() or owner._maintenance_active()
                or not owner._maintenance_cleanup_verified()):
            raise ValueError("NATIVE_RESET_REQUIRES_DUAL_PAUSED_DRAINED")

    def _native_reset_precondition(self):
        manifest = self._native_reset_manifest()
        prefix = {table:self._native_reset_table_prefix(table) for table in ("orders","order_fills","audit")}
        value = dict(schema="NATIVE_SIM_RESET_PRECONDITION_R1", old_account_id=self.engine._get("best_account", None),
            strategy_id=self.strategy_id, budget=self.budget, mode=self.engine.mode,
            settings_sha256=self._content_sha(manifest), ledger_prefix=prefix)
        return self._content_sha(value)

    def native_reset_precondition(self):
        owner = getattr(self,"_maintenance_owner",None)
        with (owner.lock if owner is not None else nullcontext()), self.lock, self.engine.lock:
            self._native_reset_require_idle(owner)
            return dict(schema="NATIVE_SIM_RESET_PRECONDITION_R1", old_account_id=self.engine._get("best_account",None),
                strategy_id=self.strategy_id, budget=self.budget, expected_precondition_sha256=self._native_reset_precondition(),
                running=dict(cohort=bool(owner is not None and not owner.stop_event.is_set()),broker=not self.stop_event.is_set()),
                native_probe_performed=False)

    @staticmethod
    def _native_reset_ack(record, *, idempotent):
        return dict(schema="NATIVE_SIM_RESET_ADOPTION_ACK_R1", reset_id=record["reset_id"],
            old_account_id=record["old_account_id"], new_account_id=record["new_account_id"],
            target_strategy_id=record["target_strategy_id"], budget=record["budget"], phase="ADOPTED_PAUSED",
            adoption_sha256=BestBroker._content_sha(record), archive_manifest_sha256=record["archive_manifest_sha256"],
            applied=True,idempotent=idempotent,orders_created=0,running=False)

    def _native_reset_summary(self):
        row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_native_reset_epoch' "
            "AND typeof(value)='text' AND length(CAST(value AS BLOB)) BETWEEN 1 AND 1048576").fetchone()
        if row is None:
            return None
        record = json.loads(row[0])
        if not isinstance(record,dict):
            return None
        return {**{key:record.get(key) for key in ("schema","reset_id","adopted_at_utc","budget",
                    "previous_strategy_id","target_strategy_id","archive_manifest_sha256","native_snapshot_sha256")},
            "old_account_id":"****"+str(record.get("old_account_id",""))[-4:],
            "new_account_id":"****"+str(record.get("new_account_id",""))[-4:]}

    def _capital_limits(self, capital):
        return dict(max_order_notional=self.budget * 2,
            max_daily_turnover=self.budget * 4, max_position_notional=self.budget * 2,
            max_total_exposure=self.budget * 2, min_cash_reserve=capital["unused_cash"],
            max_daily_loss=capital["initial_account_equity"] * 2,
            max_orders_per_day=100, max_quote_age_seconds=30, max_spread_bps=50)

    def adopt_native_reset(self, *, reset_id, requested_at, expected_old_account_id,
            new_account_id, target_strategy_id, expected_precondition_sha256, budget, now=None):
        """Adopt one explicit retired-native replacement; never prepare or send orders."""
        clock = now or self._now()
        request = dict(reset_id=reset_id,requested_at=requested_at,expected_old_account_id=expected_old_account_id,
            new_account_id=new_account_id,target_strategy_id=target_strategy_id,
            expected_precondition_sha256=expected_precondition_sha256,budget=budget)
        if (not isinstance(clock,datetime) or clock.tzinfo is None
                or not isinstance(reset_id,str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",reset_id)
                or any(not isinstance(value,str) or not re.fullmatch(r"[1-9][0-9]{0,19}",value)
                    for value in (expected_old_account_id,new_account_id))
                or expected_old_account_id == new_account_id or target_strategy_id not in ACTIVE_PAPER_STRATEGY_IDS
                or type(budget) not in (int,float) or not math.isfinite(budget) or budget != self.budget
                or not isinstance(expected_precondition_sha256,str)
                or not re.fullmatch(r"[0-9a-f]{64}",expected_precondition_sha256)):
            raise ValueError("NATIVE_RESET_EXPLICIT_REQUEST_INVALID")
        requested = timestamp(requested_at)
        owner = getattr(self,"_maintenance_owner",None)
        with (owner.lock if owner is not None else nullcontext()), self.lock, self.engine.lock:
            prior = self.engine.db.execute("SELECT value FROM settings WHERE key=? AND typeof(value)='text' "
                "AND length(CAST(value AS BLOB)) BETWEEN 1 AND 1048576",("native_reset_receipt/"+reset_id,)).fetchone()
            if prior is None and self.engine.db.execute("SELECT 1 FROM settings WHERE key=?",("native_reset_receipt/"+reset_id,)).fetchone():
                raise ValueError("NATIVE_RESET_RECEIPT_SIZE_OR_TYPE")
            if prior is not None:
                record = json.loads(prior[0])
                if record.get("request") != request:
                    raise ValueError("NATIVE_RESET_ID_REUSED")
                current = self._native_reset_record()
                if current != record:
                    raise ValueError("NATIVE_RESET_EPOCH_SUPERSEDED")
                self._native_reset_require_idle(owner)
                return self._native_reset_ack(record,idempotent=True)
            self._native_reset_require_idle(owner)
            if requested > clock or requested < clock-timedelta(seconds=60):
                raise ValueError("NATIVE_RESET_FRESH_REQUEST_REQUIRED")
            if self.engine.db.in_transaction:
                raise ValueError("NATIVE_RESET_OWNER_TRANSACTION_PENDING")
            candidate, adopted = None, False
            try:
                with self.engine.db:
                    self.engine.db.execute("BEGIN IMMEDIATE")
                    self._pending_repair_guard()  # Prove the old paired commit before preserving its bytes.
                    old_account = self.engine._get("best_account",None)
                    old_capital = self.engine._get("best_capital",None)
                    binding = self.engine._get("best_strategy_binding",None)
                    if binding is not None:
                        self._validate_strategy_binding(binding)
                    if (old_account != expected_old_account_id or not isinstance(old_capital,dict)
                            or old_capital.get("account_id") != old_account or old_capital.get("budget") != self.budget
                            or self._native_reset_precondition() != expected_precondition_sha256
                            or self.engine.db.execute("SELECT 1 FROM orders WHERE mode='moomoo_simulate' AND account_id=? LIMIT 1",(new_account_id,)).fetchone()):
                        raise ValueError("NATIVE_RESET_PRECONDITION_CHANGED")
                    manifest = self._native_reset_manifest()
                    prefix = {table:self._native_reset_table_prefix(table) for table in ("orders","order_fills","audit")}
                    connection = self.engine.connection
                    port,firm = connection["port"],connection["security_firm"]
                    candidate = self.engine._factory(port=port,security_firm=firm,account_id=new_account_id)
                    started = time.monotonic()
                    info = candidate.probe()
                    accounts = info.get("accounts") if isinstance(info,dict) else None
                    if (not isinstance(accounts,list) or len(accounts) != 1 or not isinstance(accounts[0],dict)
                            or str(accounts[0].get("account_id")) != new_account_id
                            or accounts[0].get("market") != "US" or accounts[0].get("environment") != "SIMULATE"
                            or str(getattr(candidate,"account_id",None)) != new_account_id):
                        raise ValueError("NATIVE_RESET_UNIQUE_REPLACEMENT_SIM_REQUIRED")
                    snap = candidate.snapshot([],include_quotes=False)
                    snapshot_observed,snapshot_monotonic = self._now(),time.monotonic()
                    if (not isinstance(snapshot_observed,datetime) or snapshot_observed.tzinfo is None):
                        raise ValueError("NATIVE_RESET_OBSERVATION_CLOCK_INVALID")
                    if (not isinstance(snap,dict) or snap.get("funds_only") is not True or snap.get("quotes") != {}
                            or snap.get("positions") != {} or snap.get("open_orders") != []
                            or any(type(snap.get(key)) not in (int,float) or not math.isfinite(snap[key])
                                or snap[key] != self.budget for key in ("cash","equity"))
                            or time.monotonic()-started > 60):
                        raise ValueError("NATIVE_RESET_FRESH_EXACT_BUDGET_FLAT_REQUIRED")
                    self._native_reset_require_idle(owner)
                    old_broker = self.engine.broker
                    if old_broker is not None:
                        old_broker.close()  # Do not commit a new owner while the retired connection cannot close.
                    adopted_at = self._now()
                    if (not isinstance(adopted_at,datetime) or adopted_at.tzinfo is None
                            or adopted_at < snapshot_observed or time.monotonic()-started > 60
                            or time.monotonic()-snapshot_monotonic > 60):
                        raise ValueError("NATIVE_RESET_SNAPSHOT_EXPIRED_BEFORE_COMMIT")
                    namespace = "native_reset_archive/"+reset_id+"/"
                    if self.engine.db.execute("SELECT 1 FROM settings WHERE substr(key,1,?)=? LIMIT 1",(len(namespace),namespace)).fetchone():
                        raise ValueError("NATIVE_RESET_ARCHIVE_NAMESPACE_EXISTS")
                    archived = {key:{**value,"archive_key":namespace+key} for key,value in manifest.items()}
                    native = dict(cash=snap["cash"],equity=snap["equity"],positions={},open_orders=[],quotes={},
                        funds_only=True,observed_at_utc=snapshot_observed.isoformat())
                    capital = dict(budget=self.budget,account_id=new_account_id,unused_cash=snap["cash"]-self.budget,
                        initial_account_equity=snap["equity"],started_at=adopted_at.isoformat())
                    record = dict(schema="NATIVE_SIM_RESET_ADOPTION_R1",reset_id=reset_id,request=request,
                        adopted_at_utc=adopted_at.isoformat(),old_account_id=old_account,new_account_id=new_account_id,
                        budget=self.budget,previous_strategy_id=self.strategy_id,target_strategy_id=target_strategy_id,
                        archive_namespace=namespace,archive_manifest=archived,archive_manifest_sha256=self._content_sha(archived),
                        ledger_prefix=prefix,ledger_prefix_sha256=self._content_sha(prefix),native_snapshot=native,
                        native_snapshot_sha256=self._content_sha(native),eligible_accounts=[dict(account_id=new_account_id,market="US",environment="SIMULATE")],
                        old_pending_repair_sha256=manifest.get("pending_plan_repair",{}).get("sha256"),
                        initial_capital=capital,initial_capital_sha256=self._content_sha(capital))
                    raw = json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)
                    if len(raw.encode("utf-8")) > 1024*1024:
                        raise ValueError("NATIVE_RESET_RECEIPT_SIZE_LIMIT")
                    for key in manifest:
                        self.engine.db.execute("UPDATE settings SET key=? WHERE key=?",(namespace+key,key))
                    # Keep the paired repair marker and execution configuration byte-for-byte; old grants stay archived.
                    for key in ("pending_plan_repair","execution_delay_minutes","execution_window_seconds","allow_partial_quotes"):
                        if key in manifest:
                            self.engine.db.execute("INSERT INTO settings(key,value) SELECT ?,value FROM settings WHERE key=?",(key,namespace+key))
                    limits = {**self.engine.limits,**self._capital_limits(capital)}
                    current = dict(best_account=new_account_id,best_capital=capital,best_strategy_id=target_strategy_id,
                        best_strategy_lineage=[target_strategy_id],best_strategy_binding=self._native_reset_binding(record),
                        best_strategy_binding_history={},best_plan=None,best_execution={},active=None,best_last_error="",
                        halt_reason="",limits=limits,best_native_reset_epoch=record)
                    for key,value in current.items():
                        self.engine.db.execute("INSERT INTO settings VALUES (?,?)",(key,json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)))
                    self.engine.db.execute("INSERT INTO settings VALUES (?,?)",("native_reset_receipt/"+reset_id,raw))
                    self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(adopted_at.isoformat(),"NATIVE_SIM_RESET_ADOPTED",raw))
                    self._native_reset_require_idle(owner)
                    if time.monotonic()-started > 60 or time.monotonic()-snapshot_monotonic > 60:
                        raise ValueError("NATIVE_RESET_SNAPSHOT_EXPIRED_BEFORE_COMMIT")
                adopted = True
                self.strategy_id = target_strategy_id
                self.engine.broker,self.engine.mode,self.engine.account_id = candidate,"moomoo_simulate",new_account_id
                self.engine.connection = {**info,"connected":True,"port":port,"security_firm":firm}
                candidate.cancel_check = self._cancelled
                self.engine.limits = limits
                self.engine.active,self.engine.preview_result,self.engine.account = None,None,{}
                self.plan,self.metadata,self.prepared_at,self.last_error = None,{},0,""
                self.prewarm_state,self._prewarm_key = {},None
                self.engine.last_error,self.engine.halt_reason = "",""
                self._accept_snapshot(snap)
                self.last_snapshot_at = snapshot_monotonic
                self.status,self.reason = "STOPPED","新原生模拟账户已接管并保持暂停；等待显式准备当前冻结策略"
                return self._native_reset_ack(record,idempotent=False)
            finally:
                if candidate is not None and not adopted:
                    candidate.close()

    def _native_reset_bootstrap_record(self, epoch):
        row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_native_reset_bootstrap' "
            "AND typeof(value)='text' AND length(CAST(value AS BLOB)) BETWEEN 1 AND 1048576").fetchone()
        if row is None:
            if self.engine.db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_bootstrap'").fetchone():
                raise ValueError("NATIVE_RESET_BOOTSTRAP_RECEIPT_SIZE_OR_TYPE")
            return None
        record = json.loads(row[0])
        if (not isinstance(record,dict) or set(record) != {"schema","origin","plan_sha256"}
                or record.get("schema") != "NATIVE_RESET_BOOTSTRAP_R1"
                or self.engine.db.execute("SELECT COUNT(*) FROM audit WHERE event='NATIVE_RESET_BOOTSTRAP_PREPARED' AND detail=?",
                    (json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False),)).fetchone()[0] != 1):
            raise ValueError("NATIVE_RESET_BOOTSTRAP_AUDIT_CHANGED")
        origin = record["origin"]
        if (not isinstance(origin,dict) or set(origin) != {"kind","new_epoch","native_asof_utc","account_id","strategy_id",
                    "budget","reset_receipt_sha256","native_snapshot_sha256","calculation_signal_date",
                    "calculation_basis","not_historical_native_signal_close_snapshot"}
                or origin["kind"] != "USER_NATIVE_RESET_CASH_BOOTSTRAP"
                or origin["new_epoch"] != epoch["reset_id"] or origin["account_id"] != epoch["new_account_id"]
                or origin["strategy_id"] != epoch["target_strategy_id"] or origin["budget"] != epoch["budget"]
                or origin["reset_receipt_sha256"] != self._content_sha(epoch)
                or origin["calculation_basis"] != "SIGNAL_CLOSE"
                or origin["not_historical_native_signal_close_snapshot"] is not True
                or origin["native_snapshot_sha256"] != self._content_sha({**epoch["native_snapshot"],"observed_at_utc":origin["native_asof_utc"]})
                or not isinstance(record["plan_sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",record["plan_sha256"])
                or timestamp(origin["native_asof_utc"]) < timestamp(epoch["adopted_at_utc"])):
            raise ValueError("NATIVE_RESET_BOOTSTRAP_BINDING_CHANGED")
        saved = self.engine._get("best_plan",None)
        if saved and saved.get("metadata",{}).get("signal_date") == origin["calculation_signal_date"]:
            if (saved.get("account_state_origin") != origin or saved["metadata"].get("account_state_origin") != origin
                    or self._content_sha(saved.get("plan")) != record["plan_sha256"]):
                raise ValueError("NATIVE_RESET_BOOTSTRAP_PLAN_CHANGED")
        return record

    def _native_reset_bootstrap_origin(self, clock):
        if self.engine.db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_epoch'").fetchone() is None:
            return None
        epoch = self._native_reset_record()
        if self._native_reset_bootstrap_record(epoch) is not None:
            return None
        if (self.engine._get("best_plan",None) is not None
                or self.strategy_id != epoch["target_strategy_id"] or self.engine.account_id != epoch["new_account_id"]
                or self.engine.db.execute("SELECT 1 FROM orders WHERE mode='moomoo_simulate' AND account_id=? LIMIT 1",
                    (self.engine.account_id,)).fetchone()
                or self.snapshot.get("funds_only") is not True or self.snapshot.get("positions") != {}
                or self.snapshot.get("open_orders") != [] or self.snapshot.get("quotes") != {}
                or any(type(self.snapshot.get(key)) not in (int,float) or not math.isfinite(self.snapshot[key])
                    or self.snapshot[key] != self.budget for key in ("cash","equity"))):
            raise ValueError("NATIVE_RESET_BOOTSTRAP_FRESH_FLAT_REQUIRED")
        observed = self._now()
        if not isinstance(observed,datetime) or observed.tzinfo is None or observed < timestamp(epoch["adopted_at_utc"]):
            raise ValueError("NATIVE_RESET_BOOTSTRAP_CLOCK_INVALID")
        native = {key:self.snapshot[key] for key in ("cash","equity","positions","open_orders","quotes","funds_only")}
        native["observed_at_utc"] = observed.isoformat()
        return dict(kind="USER_NATIVE_RESET_CASH_BOOTSTRAP",new_epoch=epoch["reset_id"],native_asof_utc=observed.isoformat(),
            account_id=self.engine.account_id,strategy_id=self.strategy_id,budget=self.budget,
            reset_receipt_sha256=self._content_sha(epoch),native_snapshot_sha256=self._content_sha(native),
            calculation_basis="SIGNAL_CLOSE",not_historical_native_signal_close_snapshot=True)

    def _persist_native_reset_bootstrap(self):
        origin = getattr(self,"_native_reset_preparing_origin",None)
        if origin is None:
            return
        if (not self.plan or self.plan.get("status") != "READY"
                or type(self.plan.get("model_fit_calls")) is not int or self.plan["model_fit_calls"] != 0
                or self.plan.get("strategy_id") != self.strategy_id or not self.plan.get("source_refs")
                or self.metadata.get("data_gaps") or self.metadata.get("status") not in {"READY","OPEN_WINDOW","MISSED_OPEN"}):
            raise ValueError("NATIVE_RESET_BOOTSTRAP_CURRENT_FROZEN_PLAN_REQUIRED")
        saved = self.engine._get("best_plan",None)
        if not saved or saved.get("plan") != self.plan:
            raise ValueError("NATIVE_RESET_BOOTSTRAP_PLAN_NOT_PERSISTED")
        origin = {**origin,"calculation_signal_date":self.metadata["signal_date"]}
        self.metadata = {**self.metadata,"account_state_origin":origin}
        saved = {**saved,"metadata":self.metadata,"account_state_origin":origin}
        record = dict(schema="NATIVE_RESET_BOOTSTRAP_R1",origin=origin,plan_sha256=self._content_sha(self.plan))
        raw = json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)
        for key,value in (("best_plan",saved),("best_native_reset_bootstrap",record)):
            self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                (key,json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)))
        self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(self._now().isoformat(),"NATIVE_RESET_BOOTSTRAP_PREPARED",raw))

    def _strategy_binding_precondition(self):
        return self._content_sha(dict(strategy_id=self.strategy_id,
            account_id=self.engine._get("best_account", None), budget=self.budget,
            capital=self.engine._get("best_capital", None),
            plan=self.engine._get("best_plan", None), execution=self.engine._get("best_execution", {}),
            lineage=self.engine._get("best_strategy_lineage", [SID])))

    def bind_strategy(self, *, binding_id, requested_at, expected_strategy_id,
            target_strategy_id, expected_precondition_sha256, now=None):
        """Change the strategy owner of the same reconciled budget and positions."""
        clock = now or self._now()
        if (clock.tzinfo is None or not isinstance(binding_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", binding_id)
                or timestamp(requested_at) > clock or target_strategy_id not in ACTIVE_PAPER_STRATEGY_IDS
                or not re.fullmatch(r"[0-9a-f]{64}", str(expected_precondition_sha256))):
            raise ValueError("SIM_STRATEGY_BINDING_REQUEST_INVALID")
        with self.lock, self.engine.lock:
            history = self.engine._get("best_strategy_binding_history", {})
            prior = history.get(binding_id)
            request = dict(binding_id=binding_id, requested_at=requested_at,
                expected_strategy_id=expected_strategy_id, target_strategy_id=target_strategy_id,
                expected_precondition_sha256=expected_precondition_sha256)
            if prior:
                if prior["request"] != request:
                    raise ValueError("SIM_STRATEGY_BINDING_ID_REUSED")
                if self.strategy_id != target_strategy_id:
                    raise ValueError("SIM_STRATEGY_BINDING_SUPERSEDED")
                return self.state()
            if not self.stop_event.is_set() or self.worker and self.worker.is_alive():
                raise ValueError("SIM_STRATEGY_BINDING_REQUIRES_STOPPED")
            self.engine._require_stopped()
            self._pending_repair_guard()
            account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
            if (self.engine._pending() or self.engine.halt_event.is_set()
                    or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                    or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                    or capital.get("account_id") != account or capital.get("budget") != self.budget
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                    or time.monotonic() - self.last_snapshot_at > 60):
                raise ValueError("SIM_STRATEGY_BINDING_REQUIRES_RECONCILED_ORIGINAL_ACCOUNT")
            if (expected_strategy_id != self.strategy_id
                    or expected_precondition_sha256 != self._strategy_binding_precondition()):
                raise ValueError("SIM_STRATEGY_BINDING_PRECONDITION_CHANGED")
            if target_strategy_id == self.strategy_id:
                raise ValueError("SIM_STRATEGY_BINDING_ALREADY_CURRENT")
            self._accept_snapshot(self.snapshot)
            preserved = {key: raw for key, raw in self.engine.db.execute("SELECT key,value FROM settings")
                if key in {"best_plan", "best_execution", "best_full_liquidation_reset", "best_same_day_catchup",
                    "best_same_day_catchup_renewal", "best_first_execution", "best_manual_residual_sell",
                    "best_capital", "best_account", "automatic_completion_policy", "pending_plan_repair", "active"}}
            record = dict(schema_version=1, request=request, bound_at_utc=clock.isoformat(),
                account_id=account, budget=self.budget, previous_strategy_id=self.strategy_id,
                target_strategy_id=target_strategy_id, execution_mode="REBALANCE_EXISTING_POSITIONS",
                preserved_settings=preserved, preserved_settings_sha256=self._content_sha(preserved),
                positions_at_binding=deepcopy(self.snapshot["positions"]),
                strategy_cash_at_binding=self.snapshot["cash"] - capital["unused_cash"])
            lineage = list(dict.fromkeys([*self.engine._get("best_strategy_lineage", [SID]), target_strategy_id]))
            history[binding_id] = record
            with self.engine.db:
                for key, value in (("best_strategy_id", target_strategy_id), ("best_strategy_lineage", lineage),
                        ("best_strategy_binding", record), ("best_strategy_binding_history", history),
                        ("best_plan", None), ("best_execution", {}), ("active", None)):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                        (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(),
                    "SIM_STRATEGY_BOUND", json.dumps(record, ensure_ascii=False, allow_nan=False)))
            self.strategy_id = target_strategy_id
            self.engine.active, self.engine.preview_result = None, None
            self.plan, self.metadata = None, {}
            self.prepared_at = 0
            self.status, self.reason = "STOPPED", "已绑定原模拟账户策略；按现有持仓与资金差额调仓，等待合格信号与执行窗口"
            return self.state()

    def _scoped_legacy_setting(self, key, default=None):
        original_binding = self.engine._get("best_strategy_binding", None) is None
        return self.engine._get(key, default) if self.strategy_id == SID and original_binding else default

    def _scheduled_open(self, value):
        return timestamp(value) + timedelta(minutes=self.execution_delay_minutes)

    @staticmethod
    def _content_sha(value):
        return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()

    def prepare_full_liquidation_reset(self, reset_request, now=None):
        """Freeze an explicitly requested clean restart; preparation never sends an order."""
        self._require_legacy_strategy()
        with self.lock:
            clock = now or self._now()
            if clock.tzinfo is None:
                raise ValueError("RESET_CLOCK_TIMEZONE_REQUIRED")
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("RESET_REQUIRES_STOPPED_EXECUTION")
            self.engine._require_stopped()
            if self.engine._pending() or self.engine.halt_event.is_set():
                raise ValueError("RESET_REQUIRES_RECONCILED_ORIGINAL_ACCOUNT")
            required = {"reset_id", "requested_at", "strategy_ids", "signal_date",
                        "expected_policy_id", "expected_package_sha256"}
            if (not isinstance(reset_request, dict) or set(reset_request) != required
                    or not isinstance(reset_request["reset_id"], str)
                    or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_request["reset_id"])
                    or reset_request["expected_policy_id"] != "HGB_TOP20_RISK_R1"
                    or not isinstance(reset_request["strategy_ids"], list)
                    or self.strategy_id not in reset_request["strategy_ids"]
                    or len(set(reset_request["strategy_ids"])) != len(reset_request["strategy_ids"])
                    or not set(reset_request["strategy_ids"]).issubset({self.strategy_id, "HGB_FACTOR_5"})
                    or not isinstance(reset_request["expected_package_sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", reset_request["expected_package_sha256"])):
                raise ValueError("RESET_REQUEST_IDENTITY_INVALID")
            if timestamp(reset_request["requested_at"]) > clock:
                raise ValueError("RESET_REQUEST_FUTURE_TIME")
            if self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes:
                raise ValueError("RESET_REQUIRES_OPEN_TEN_MINUTE_MARKET_POLICY")
            account = self.engine._get("best_account", None)
            capital = self.engine._get("best_capital", None)
            if (not isinstance(account, str) or not account or not isinstance(capital, dict)
                    or capital.get("account_id") != account or capital.get("budget") != self.budget):
                raise ValueError("RESET_ORIGINAL_ACCOUNT_BUDGET_REQUIRED")
            self._connect()  # Original SIMULATE identity, actual quantities and funds; no quotes or orders.
            if self.engine.mode != "moomoo_simulate" or self.engine.account_id != account:
                raise ValueError("RESET_ORIGINAL_SIMULATE_ACCOUNT_REQUIRED")
            from .applied_source import _reset_request
            request = deepcopy(reset_request)
            request["strategy_ids"] = [self.strategy_id]
            request = _reset_request(request, now=clock)
            request_sha = self._content_sha(request)
            prior = self._scoped_legacy_setting("best_full_liquidation_reset", None)
            if prior and prior.get("reset_id") == request["reset_id"]:
                if prior.get("request_sha256") != request_sha:
                    raise ValueError("RESET_REQUEST_CHANGED")
                saved = self.engine._get("best_plan", None)
                if not saved:
                    raise ValueError("RESET_FROZEN_PLAN_REQUIRED")
                self.plan, self.metadata = saved["plan"], saved["metadata"]
                self._active_full_reset()
                self.status, self.reason = "WAITING_OPEN", "已冻结清仓后重买目标；等待下一个开盘窗口"
                return self.state()
            if prior and prior.get("stage") != "COMPLETED":
                raise ValueError("RESET_ALREADY_PENDING")
            snapshot = self.engine.broker.snapshot([], include_quotes=False)
            if snapshot.get("funds_only") is not True or snapshot.get("quotes") != {}:
                raise ValueError("RESET_FUNDS_ONLY_SNAPSHOT_REQUIRED")
            self._accept_snapshot(snapshot)
            loaded = self.source.load(states=None, now=clock, reset_request=request)
            metadata = {key: value for key, value in loaded.items() if key != "plans"}
            plan = deepcopy(loaded.get("plans", {}).get(self.strategy_id))
            opening = timestamp(metadata["next_open_utc"])
            close = timestamp(metadata["signal_close_utc"])
            package = (metadata.get("source_refs") or {}).get("selected/package.json", {})
            if (metadata.get("status") not in {"READY", "OPEN_WINDOW"} or metadata.get("data_gaps")
                    or clock >= opening or close > clock or close >= opening
                    or metadata.get("signal_date") != request["signal_date"]
                    or metadata.get("execution_date") != opening.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    or not isinstance(plan, dict) or plan.get("policy_id") != request["expected_policy_id"]
                    or plan.get("signal_date") != request["signal_date"]
                    or plan.get("execution_date") != metadata.get("execution_date")
                    or close.astimezone(ZoneInfo("America/New_York")).date().isoformat() != request["signal_date"]
                    or package.get("sha256") != request["expected_package_sha256"]
                    or plan.get("model_fit_calls", 0) != 0):
                raise ValueError("RESET_FROZEN_DIRECT_TARGET_BINDING_INVALID")
            weights = [float(row["target_weight"]) for row in plan.get("rows", [])]
            codes = [row["code"] for row in plan.get("rows", [])]
            cash = float(plan["target_cash_weight"])
            if (not weights or len(codes) != len(set(codes)) or any(not code_valid(code) for code in codes)
                    or any(not math.isfinite(weight) or not 0 <= weight <= .100001 for weight in weights)
                    or not math.isfinite(cash) or not 0 <= cash <= 1
                    or abs(sum(weights) + cash - 1) > 1e-7):
                raise ValueError("RESET_DIRECT_TARGET_WEIGHTS_INVALID")
            plan.update(reset_id=request["reset_id"], execution_mode="FULL_LIQUIDATION_THEN_REBUY")
            metadata.update(reset_id=request["reset_id"], execution_mode="FULL_LIQUIDATION_THEN_REBUY")
            archive = self.engine._get("best_reset_archive", {})
            if request["reset_id"] in archive:
                raise ValueError("RESET_ID_ALREADY_ARCHIVED")
            archive[request["reset_id"]] = {
                "archived_at": clock.isoformat(), "best_plan": self.engine._get("best_plan", None),
                "best_execution": self.engine._get("best_execution", {}),
                "best_same_day_catchup": self._scoped_legacy_setting("best_same_day_catchup", None),
                "actual_positions": deepcopy(snapshot["positions"]), "actual_cash": snapshot["cash"]}
            record = dict(schema_version=1, reset_id=request["reset_id"], request=request,
                request_sha256=request_sha, account_id=account, signal_date=request["signal_date"],
                execution_date=metadata["execution_date"], policy_id=request["expected_policy_id"],
                expected_package_sha256=request["expected_package_sha256"], prepared_at=clock.isoformat(),
                stage="ARMED", plan_sha256=self._content_sha(plan), metadata_sha256=self._content_sha(metadata),
                starting_positions={code: item["qty"] for code, item in snapshot["positions"].items() if item["qty"]},
                unused_cash=capital["unused_cash"], budget=self.budget, post_liquidation_baseline=None)
            with self.engine.db:
                for key, value in (("best_reset_archive", archive),
                                   ("best_plan", {"metadata": metadata, "plan": plan, "close_state": None}),
                                   ("best_execution", {}), ("best_same_day_catchup", None),
                                   ("best_full_liquidation_reset", record)):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
            self.plan, self.metadata = plan, metadata
            self.prepared_at = time.monotonic()
            self.status, self.reason = "WAITING_OPEN", "已冻结清仓后重买目标；当前持仓仍保留，等待下一开盘"
            self.engine._audit("FULL_LIQUIDATION_RESET_PREPARED", json.dumps({
                "reset_id": record["reset_id"], "signal_date": record["signal_date"],
                "execution_date": record["execution_date"], "order_submissions": 0,
                "starting_position_count": len(record["starting_positions"])}))
            return self.state()

    def cancel_full_liquidation_reset(self, reset_id, now=None):
        """Withdraw only an unstarted reset; leave the real account and receipts intact."""
        self._require_legacy_strategy()
        with self.lock:
            clock = timestamp((now or self._now()).isoformat())
            if not isinstance(reset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_id):
                raise ValueError("RESET_CANCEL_ID_REQUIRED")
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("RESET_CANCEL_REQUIRES_STOPPED_EXECUTION")
            self.engine._require_stopped()
            if self.engine._pending() or self.engine.halt_event.is_set():
                raise ValueError("RESET_CANCEL_REQUIRES_RECONCILED_ACCOUNT")
            archive = self.engine._get("best_reset_archive", {})
            record = self._scoped_legacy_setting("best_full_liquidation_reset", {})
            if not record:
                if isinstance(archive.get(reset_id), dict) and archive[reset_id].get("cancellation"):
                    return self.state()  # A repeat must not erase a later normal rebalance plan.
                raise ValueError("RESET_CANCEL_ACTIVE_ID_REQUIRED")
            if record.get("reset_id") != reset_id:
                raise ValueError("RESET_CANCEL_ACTIVE_ID_REQUIRED")
            if record.get("stage") != "ARMED" or record.get("post_liquidation_baseline") is not None:
                raise ValueError("RESET_CANCEL_ONLY_UNSTARTED_LIQUIDATION")
            saved = self.engine._get("best_plan", None)
            if not isinstance(saved, dict) or not isinstance(archive.get(reset_id), dict):
                raise ValueError("RESET_CANCEL_FROZEN_HISTORY_REQUIRED")
            before = self.plan, self.metadata
            self.plan, self.metadata = saved["plan"], saved["metadata"]
            try:
                self._active_full_reset(allow_disconnected=True)
                prepared = timestamp(record["prepared_at"])
                if clock < prepared:
                    raise ValueError("RESET_CANCEL_CLOCK_PRECEDES_PREPARATION")
                execution = self.engine._get("best_execution", {})
                strategy = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (self.strategy_id,)).fetchone()
                manifest = json.loads(strategy[0]) if strategy else None
                asofs = {execution.get("phase_asof")}
                for candidate in (execution.get("manifest"), manifest):
                    if isinstance(candidate, dict):
                        origin = json.loads(candidate.get("source", "{}"))
                        if origin.get("reset_id") == reset_id:
                            asofs.add(candidate.get("asof"))
                asofs.discard(None)
                rows = self.engine.db.execute(
                    "SELECT o.*,f.payload AS fill FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
                    "WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=?",
                    (self.strategy_id, record["account_id"]))
                for row in rows:
                    if row["status"] == "CANCELLED_BEFORE_SEND" and row["order_id"] is None and row["fill"] is None:
                        continue  # Keep the durable, definitely-unsent intention as history.
                    reset_order = False
                    for asof in asofs:
                        for phase in ("SELL", "BUY"):
                            for generation in range(MAX_TERMINAL_RETRIES_PER_CODE + 1):
                                identity = [row["mode"], row["account_id"], self.strategy_id, asof, row["code"], "reset", reset_id, phase]
                                if generation:
                                    identity.append(generation)
                                if hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:32] == row["id"]:
                                    reset_order = True
                    if reset_order or timestamp(row["created_at"]) >= prepared:
                        raise ValueError("RESET_CANCEL_SUBMITTED_ORDER_EXISTS")
                cancellation = dict(cancelled_at=clock.isoformat(),
                    reason="USER_CANCELLED_FULL_LIQUIDATION_KEEP_POSITIONS_REBALANCE",
                    replacement_mode="EXISTING_POSITIONS_REBALANCE", order_submissions=0,
                    full_liquidation_reset=deepcopy(record), best_plan=deepcopy(saved),
                    best_execution=deepcopy(execution), active_manifest=deepcopy(manifest),
                    best_same_day_catchup=self._scoped_legacy_setting("best_same_day_catchup", None),
                    subscription_prewarm=deepcopy(self.prewarm_state), last_error=self.last_error)
                archive[reset_id]["cancellation"] = cancellation
                with self.engine.db:
                    for key, value in (("best_reset_archive", archive), ("best_full_liquidation_reset", {}),
                                       ("best_plan", None), ("best_execution", {}),
                                       ("best_same_day_catchup", None), ("best_subscription_prewarm", {})):
                        self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                                               (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                    self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(),
                        "FULL_LIQUIDATION_RESET_CANCELLED", json.dumps(dict(reset_id=reset_id,
                        reason=cancellation["reason"], replacement_mode=cancellation["replacement_mode"],
                        order_submissions=0), ensure_ascii=False)))
            except Exception:
                self.plan, self.metadata = before
                raise
            self.plan, self.metadata, self.prepared_at = None, {}, 0.0
            self.prewarm_state, self._prewarm_key = {}, None
            self.status, self.reason = "STOPPED", "已撤销全卖重买；保留现有持仓，等待按实际账户生成正常调仓方案"
            return self.state()

    @staticmethod
    def _published_target_binding(plan, frozen, current):
        """Keep a one-time published target bound to the original lightweight source."""
        keys = ({"consensus/publication", "consensus/flags", "consensus/pool"}
                if plan.get("published_target_alignment_id") is not None and plan.get("strategy_id") not in LEGACY_PAPER_STRATEGY_IDS
                else {"frozen_calendar", "session_hours_rules", "daily/report.json",
                      "selected/package.json", "selected/current_report.json", "current/features.parquet"})
        refs, live = frozen.get("source_refs"), current.get("source_refs")
        if (not isinstance(refs, dict) or not isinstance(live, dict) or not keys.issubset(live)
                or plan.get("source_refs") != refs
                or any(key not in refs or refs[key] != value for key, value in live.items())
                or current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                or (current.get("status") != "MISSED_OPEN" and current.get("ready") is not True)
                or current.get("data_gaps") or current.get("source_date") != frozen.get("signal_date")
                or any(current.get(key) != frozen.get(key) for key in
                       ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))):
            raise ValueError("PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED")

    @staticmethod
    def _closed_history_binding(plans, frozen, current, archive_ref, *, account_state_plans=False, account_states=None):
        """Verify chart-only bytes against the existing immutable decision archive."""
        from .cohort import Cohort
        reason = "PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED"
        old, live = frozen.get("source_refs", {}), current.get("source_refs", {})
        package_key = "selected/package.json"
        if (not isinstance(old, dict) or not isinstance(live, dict) or set(live) - set(old)
                or package_key not in live or package_key not in old
                or any(old.get(key) != value for key, value in live.items() if key != package_key)
                or old[package_key].get("path") != live[package_key].get("path")):
            raise ValueError(reason)
        def bound(ref):
            path = Path(ref["path"])
            if path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError(reason)
            raw = path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref["sha256"]:
                raise ValueError(reason)
            return json.loads(raw)
        try:
            # Verify all the original economic inputs, including refs omitted by lightweight status.
            for key, ref in old.items():
                if key != package_key and Cohort._file_sha(Path(ref["path"])) != ref["sha256"]:
                    raise ValueError(reason)
            archived, package = bound(archive_ref), bound(live[package_key])
            day = frozen["signal_date"]
            history_key = "history/" + day + ".json"
            snapshot_ref = package["source_refs"][history_key]
            if snapshot_ref["sha256"] != archived["source_hashes"][history_key]:
                raise ValueError(reason)
            snapshot = bound(snapshot_ref)
            from .applied_source import LEGACY_POLICY
            snapshot_policy = snapshot.get("policy_id", LEGACY_POLICY if account_state_plans else None)
            protected = {key: value for key, value in archived["source_hashes"].items()
                if key.startswith(("frozen/", "current/", "policy/")) or key == history_key}
            scores = archived["scores"]
            if (not protected or package.get("model_fit_calls") != 0
                    or package.get("broker_action_allowed") is not False
                    or snapshot.get("signal_date") != day or package.get("policy_id") != snapshot_policy
                    or any(package["source_hashes"].get(key) != value for key, value in protected.items())
                    or set(scores) != {"current", "model_id", "model_sha256", "ranking_basis", "scoring_scope"}
                    or scores != {key: package["shared_scores"].get(key) for key in scores}
                    or snapshot["shared_scores"]["rows"] != scores["current"]["rows"]):
                raise ValueError(reason)
            def targets(value):
                pairs = [(row.get("ticker") or row["code"].removeprefix("US."), row["target_weight"]) for row in value["rows"]]
                if len(dict(pairs)) != len(pairs):
                    raise ValueError(reason)
                return dict(pairs), value["target_cash_weight"]
            for sid, original in snapshot["applications"].items():
                application = package["strategies"][sid]["application"]
                if (application.get("status") != "READY" or application.get("signal_date") != day
                        or application.get("policy_id") != snapshot_policy
                        or targets(application) != targets(original)):
                    raise ValueError(reason)
            if account_state_plans:
                # The published CASH_START application remains sealed above. A normal
                # LEGACY account plan instead belongs to its original close-state archive.
                from .applied_source import LEGACY_POLICY, _state, _PROVENANCE
                if (package.get("policy_id") != LEGACY_POLICY or archived.get("model_fit_calls") != 0
                        or archived.get("source_date") != day
                        or archived.get("execution_date") != frozen.get("execution_date")
                        or archived.get("next_open_utc") != frozen.get("next_open_utc")
                        or (frozen.get("next_close_utc") is not None
                            and archived.get("next_close_utc") != frozen["next_close_utc"])
                        or archived.get("source_refs") != old or archived.get("plans") != plans
                        or set(archived.get("states", {})) != set(plans)
                        or not isinstance(account_states, dict) or set(account_states) != set(plans)
                        or archived["states"] != {sid: _state(account_states[sid], day) for sid in plans}
                        or archived.get("provenance") != _PROVENANCE):
                    raise ValueError(reason)
                for sid, plan in plans.items():
                    state = _state(archived["states"][sid], day)
                    before = {row.get("ticker") or row["code"].removeprefix("US."): row["weight_before"]
                              for row in plan["rows"] if row["weight_before"] > 0}
                    if (state != archived["states"][sid] or before != state["weights"]
                            or plan.get("cash_weight_before") != state["cash_weight"]
                            or plan.get("source_hashes") != archived["source_hashes"]
                            or plan.get("source_refs") != old
                            or plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY
                            or plan.get("strategy_id") != sid or plan.get("status") != "READY"
                            or plan.get("signal_date") != day or plan.get("source_date") != day
                            or plan.get("execution_date") != frozen.get("execution_date")
                            or plan.get("valuation_basis") != "SIGNAL_CLOSE"
                            or plan.get("execution_status") != "TARGET_ONLY"
                            or plan.get("model_fit_calls") != 0 or plan.get("broker_action_allowed") is not False
                            or plan.get("provenance") != _PROVENANCE
                            or set(plan) & {"reset_id", "reset_request", "assumed_states", "execution_mode",
                                            "execution_condition", "open_prices", "future_prices"}):
                        raise ValueError(reason)
            else:
                for sid, plan in plans.items():
                    if (plan.get("policy_id") != package.get("policy_id")
                            or targets(plan) != targets(snapshot["applications"][sid])
                            or targets(plan) != targets(archived["plans"][sid])):
                        raise ValueError(reason)
        except (KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(reason) from exc

    @staticmethod
    def _first_execution_display_binding(plans, frozen, current, source, *, account_states=None, expected=None,
                                         allow_closed_display=False):
        """Bind a chart-only replacement to the original LEGACY account decision."""
        from .cohort import Cohort
        reason = "FIRST_EXECUTION_DISPLAY_BINDING_CHANGED"
        try:
            Cohort._match_source_refs(frozen.get("source_refs"), current, reason)
        except ValueError:
            pass
        else:
            if expected is not None:
                raise ValueError(reason)
            return None
        try:
            from .applied_source import LEGACY_POLICY
            root = Path(source.runtime_root).resolve()
            policies = {plan["policy_id"] for plan in plans.values() if plan.get("policy_id") is not None}
            if policies and policies != {LEGACY_POLICY}:
                raise ValueError(reason)
            # Follow the existing DailySource archive location rule, never search
            # for a convenient archive or cross another account's owner root.
            day_root = (root / frozen["signal_date"]).resolve()
            policy_day_root = (root / "policies" / LEGACY_POLICY / frozen["signal_date"]).resolve()
            archive_path = (policy_day_root if policies else day_root) / "plans.json"
            explicit = frozen.get("archive")
            if explicit is not None:
                archive_path = Path(explicit["path"]).resolve()
                if not any(archive_path.is_relative_to(base) for base in (day_root, policy_day_root)):
                    raise ValueError(reason)
            if archive_path.stat().st_size > 10 * 1024 * 1024:
                raise ValueError(reason)
            archive_ref = {"path": str(archive_path),
                           "sha256": Cohort._file_sha(archive_path)}
            if explicit is not None and explicit != archive_ref:
                raise ValueError(reason)
            BestBroker._closed_history_binding(plans, frozen, current, archive_ref, account_state_plans=True,
                account_states=account_states)
            proof = {"schema_version": 1, "kind": "SAME_SIGNAL_LEGACY_ACCOUNT_DISPLAY_EQUIVALENCE",
                     "original_package_ref": frozen["source_refs"]["selected/package.json"],
                     "accepted_package_ref": current["source_refs"]["selected/package.json"],
                     "archive_ref": archive_ref,
                     "plan_sha256_by_strategy": {sid: _first_execution_sha(plan) for sid, plan in plans.items()}}
            if expected is not None:
                compared = dict(proof)
                if allow_closed_display:
                    # Only the caller's expired/no-pending read path may validate a
                    # later equivalent display package. The stored proof never changes.
                    compared["accepted_package_ref"] = expected.get("accepted_package_ref")
                if compared != expected:
                    raise ValueError(reason)
            return proof
        except (AttributeError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
            raise ValueError(reason) from exc

    def _closed_execution(self, saved, now):
        """Recognize only the old same-session intent after every registered deadline."""
        metadata = saved.get("metadata", {})
        state = self.engine._get("best_execution", {})
        if (self.engine._pending() or state.get("signal_date") != metadata.get("signal_date")
                or state.get("phase") not in {"BUY", "SELL", "DONE"}
                or not (state.get("processed_codes") or state.get("phase") == "DONE")
                or now.astimezone(ZoneInfo("America/New_York")).date().isoformat() != metadata.get("execution_date")
                or now < self._scheduled_open(metadata["next_open_utc"]) + timedelta(seconds=self.execution_window_seconds)):
            return False
        before = self.plan, self.metadata
        try:
            self.plan, self.metadata = saved["plan"], metadata
            manual = self._manual_completion_record()
            if manual is not None and now < timestamp(manual["deadline_utc"]):
                return False
            automatic = self._automatic_completion(now)
            if automatic is not None and now < automatic[1]:
                return False
        finally:
            self.plan, self.metadata = before
        first = self._scoped_legacy_setting("best_first_execution", None)
        if isinstance(first, dict) and first.get("signal_date") == metadata.get("signal_date"):
            before = self.plan, self.metadata
            try:
                self.plan, self.metadata = saved["plan"], metadata
                deadline = self._first_execution_end(now, allow_closed_source=True)
                if deadline is not None and now < deadline:
                    return False
            finally:
                self.plan, self.metadata = before
        record = self._scoped_legacy_setting("best_same_day_catchup", None)
        if isinstance(record, dict) and record.get("signal_date") == metadata.get("signal_date"):
            if now < timestamp(record["deadline_utc"]):
                return False
            before = self.plan, self.metadata
            try:
                self.plan, self.metadata = saved["plan"], metadata
                deadline = self._catchup_end()  # Validate the original permission; never renew it.
                if state.get("phase") != "DONE" and deadline is None:
                    raise ValueError("EXPIRED_MANUAL_PERMISSION_INVALID")
                if deadline is not None and now < deadline:
                    return False  # Only the independently validated explicit renewal may reopen this intent.
            finally:
                self.plan, self.metadata = before
        return True

    def _target_alignment_precondition(self):
        positions = {code: value.get("qty", 0) for code, value in self.snapshot.get("positions", {}).items()}
        return self._content_sha(dict(strategy_id=self.strategy_id,
            account_id=self.engine._get("best_account", None), budget=self.budget,
            capital=self.engine._get("best_capital", None), plan=self.engine._get("best_plan", None),
            execution=self.engine._get("best_execution", {}), active=self.engine._get("active", None),
            requested_state=self.engine._get("best_requested_strategy_state", {}),
            target_conversion=self.engine._get("best_published_target_conversion", None),
            alignment_id=(self.engine._get("best_published_target_alignment", None) or {}).get("request", {}).get("alignment_id"),
            positions=positions, cash=self.snapshot.get("cash")))

    def _alignment_record(self, alignment_id):
        rows = self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_ALIGNED' "
            "AND json_extract(detail,'$.request.alignment_id')=? ORDER BY rowid DESC LIMIT 2", (alignment_id,)).fetchall()
        if len(rows) > 1:
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_AUDIT_AMBIGUOUS")
        if not rows:
            return None
        if len(rows[0][0].encode("utf-8")) > 2 * 1024 * 1024:
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_AUDIT_SIZE")
        return json.loads(rows[0][0])

    def _target_conversion(self):
        state = self.engine._get("best_published_target_conversion", None)
        if state is None: return None
        if not isinstance(state, dict) or state.get("status") not in {"ACTIVE", "COMPLETED"}:
            raise ValueError("PUBLISHED_TARGET_CONVERSION_STATE_INVALID")
        row = self.engine.db.execute("SELECT detail FROM audit WHERE event IN "
            "('PUBLISHED_TARGET_CONVERSION_AUTHORIZED','PUBLISHED_TARGET_CONVERSION_STATE') "
            "AND json_extract(detail,'$.conversion_id')=? ORDER BY rowid DESC LIMIT 1", (state.get("conversion_id"),)).fetchone()
        origin, latest = self._alignment_record(state.get("origin_alignment_id")), self._alignment_record(state.get("last_alignment_id"))
        capital = self.engine._get("best_capital", {})
        if (not row or len(row[0].encode("utf8")) > 32768 or json.loads(row[0]) != state
                or not origin or not latest or self._content_sha(origin) != state.get("origin_alignment_sha256")
                or self._content_sha(latest) != state.get("last_alignment_sha256")
                or state.get("account_id") != self.engine._get("best_account", None)
                or state.get("budget") != self.budget or capital.get("budget") != self.budget
                or capital.get("account_id") != state.get("account_id")
                or state.get("strategy_id") != origin.get("strategy_id") or latest.get("strategy_id") != state.get("strategy_id")
                or latest.get("signal_date") != state.get("last_signal_date")
                or latest.get("execution_date") != state.get("last_execution_date")
                or latest.get("published_target_sha256") != state.get("last_published_target_sha256")):
            raise ValueError("PUBLISHED_TARGET_CONVERSION_AUDIT_OR_BINDING_CHANGED")
        if state["status"] == "COMPLETED": return None
        if (state.get("strategy_id") != self.strategy_id or self.engine._get("best_published_target_alignment", None) != latest):
            raise ValueError("PUBLISHED_TARGET_CONVERSION_CURRENT_ALIGNMENT_CHANGED")
        return state

    @staticmethod
    def _conversion_authorization(record, conversion_id, requested_at):
        return dict(schema="OWNER_PUBLISHED_TARGET_CONVERSION_R1", conversion_id=conversion_id, status="ACTIVE",
            strategy_id=record["strategy_id"], account_id=record["account_id"], budget=record["budget"], requested_at=requested_at,
            origin_alignment_id=record["request"]["alignment_id"], origin_alignment_sha256=BestBroker._content_sha(record),
            last_alignment_id=record["request"]["alignment_id"], last_alignment_sha256=BestBroker._content_sha(record),
            last_signal_date=record["signal_date"], last_execution_date=record["execution_date"],
            last_published_target_sha256=record["published_target_sha256"],
            authorized_at=record["prepared_at"], updated_at=record["prepared_at"], target_origin="COHORT_CURRENT_FROZEN_OWNER",
            completion_rule="RECONCILED_OFF_TARGET_ZERO_AND_BUY_EXECUTED")

    def authorize_target_conversion(self, *, conversion_id, alignment_id, requested_at, expected_precondition_sha256, now=None):
        """Audit continuation of an existing explicit alignment; do not change plan/orders."""
        clock = now or self._now()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(conversion_id)) or timestamp(requested_at) > clock:
            raise ValueError("PUBLISHED_TARGET_CONVERSION_REQUEST_INVALID")
        with self.lock, self.engine.lock:
            existing = self.engine._get("best_published_target_conversion", None)
            if existing is not None:
                self._target_conversion()
                if (existing.get("conversion_id") == conversion_id and existing.get("origin_alignment_id") == alignment_id
                        and existing.get("requested_at") == requested_at): return self.state()
                raise ValueError("PUBLISHED_TARGET_CONVERSION_ALREADY_BOUND")
            if (not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                    or self.engine._pending() or self.engine.halt_event.is_set() or self.snapshot.get("funds_only") is not True
                    or self.snapshot.get("open_orders") != [] or time.monotonic() - self.last_snapshot_at > 60
                    or self._target_alignment_precondition() != expected_precondition_sha256):
                raise ValueError("PUBLISHED_TARGET_CONVERSION_REQUIRES_STOPPED_FRESH_RECONCILE")
            saved = self.engine._get("best_plan", {})
            if saved.get("plan", {}).get("published_target_alignment_id") != alignment_id:
                raise ValueError("PUBLISHED_TARGET_CONVERSION_ORIGINAL_ALIGNMENT_REQUIRED")
            record = self._aligned_target_receipt(saved["plan"], saved["metadata"])
            state = self._conversion_authorization(record, conversion_id, requested_at)
            state.update(authorized_at=clock.isoformat(), updated_at=clock.isoformat())
            with self.engine.db:
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_published_target_conversion", json.dumps(state, ensure_ascii=False, allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(), "PUBLISHED_TARGET_CONVERSION_AUTHORIZED", json.dumps(state, ensure_ascii=False, allow_nan=False)))
            return self.state()

    def _verified_manual_completion_record(self):
        record = self.engine._get("best_published_target_manual_completion", None)
        if record is None:
            return None
        rows = self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
            "AND json_extract(detail,'$.request.manual_id')=? LIMIT 2", (record.get("manual_id"),)).fetchall()
        if len(rows) != 1 or json.loads(rows[0][0]) != record:
            raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_AUDIT_CHANGED")
        return record

    def _native_manual_clock(self, metadata, *, record=None):
        """Bind this manual grant to the ordinary owner clock without changing it."""
        if (type(self.execution_delay_minutes) is not int or type(self.execution_window_seconds) is not int
                or (self.execution_delay_minutes, self.execution_window_seconds) not in ((0, 600), (30, 600), (25, 1500))
                or self.allow_partial_quotes is not True):
            raise ValueError("NATIVE_MANUAL_ORDINARY_CLOCK_CHANGED")
        clock = dict(execution_delay_minutes=self.execution_delay_minutes,
            execution_time_utc=self._scheduled_open(metadata["next_open_utc"]).isoformat(),
            execution_window_seconds=self.execution_window_seconds)
        if record is not None:
            signed = record.get("ordinary_execution_clock")
            # Legacy receipts were issued only at delay 0. They never inherit 30.
            if ((signed is None and self.execution_delay_minutes != 0)
                    or signed is not None and signed != clock):
                raise ValueError("NATIVE_MANUAL_ORDINARY_CLOCK_CHANGED")
        return clock

    def _native_manual_binding(self, plan, metadata, *, clock=None, source=False):
        """Current successor plan custody; never reuse the bootstrap timing grant."""
        from .cohort import Cohort
        epoch = self._native_reset_record()
        bootstrap = self._native_reset_bootstrap_record(epoch)
        saved = self.engine._get("best_plan", {})
        self._require_original_manual_account()
        self._native_manual_clock(metadata)
        if (self.strategy_id != "R10_DIRECT_H5_RIDGE_MID" or epoch["target_strategy_id"] != self.strategy_id
                or not bootstrap or metadata.get("signal_date", "") <= bootstrap["origin"]["calculation_signal_date"]
                or self.budget != 10000 or epoch["new_account_id"] != self.engine.account_id
                or not plan or plan != saved.get("plan") or plan != self.plan or metadata != saved.get("metadata")
                or plan.get("strategy_id") != self.strategy_id or plan.get("status") != "READY"
                or type(plan.get("model_fit_calls")) is not int or plan["model_fit_calls"] != 0
                or metadata.get("data_gaps") or metadata.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                or self._native_first_record(clock) is not None):
            raise ValueError("NATIVE_MANUAL_CURRENT_PLAN_BINDING_CHANGED")
        archive = metadata.get("archive")
        from .applied_source import _reference
        if not isinstance(archive, dict) or set(archive) != {"path", "sha256"}:
            raise ValueError("NATIVE_MANUAL_SOURCE_ARCHIVE_REQUIRED")
        _reference(archive["path"], archive["sha256"])
        if source:
            current = Cohort._book_source_data(self.strategy_id, self.source.status(now=clock))
            if (current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or current.get("data_gaps")
                    or any(current.get(k) != metadata.get(k) for k in
                        ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "next_close_utc"))):
                raise ValueError("NATIVE_MANUAL_CURRENT_SOURCE_CHANGED")
            Cohort._match_source_refs(plan.get("source_refs"), current, "NATIVE_MANUAL_CURRENT_SOURCE_CHANGED")
        return epoch, bootstrap

    def _native_manual_record(self, record, plan, metadata):
        epoch, bootstrap = self._native_manual_binding(plan, metadata)
        self._native_manual_clock(metadata, record=record)
        capital = self.engine._get("best_capital", {})
        if (record.get("strategy_id") != self.strategy_id or record.get("account_id") != epoch["new_account_id"]
                or record.get("budget") != self.budget or record.get("unused_cash") != capital.get("unused_cash")
                or record.get("reset_receipt_sha256") != self._content_sha(epoch)
                or record.get("bootstrap_sha256") != self._content_sha(bootstrap)
                or record.get("plan_sha256") != self._content_sha(plan)
                or record.get("metadata_sha256") != self._content_sha(metadata)
                or record.get("source_archive") != metadata.get("archive")
                or record.get("source_refs_sha256") != self._content_sha(plan.get("source_refs"))
                or any(record.get(k) != metadata.get(k) for k in
                    ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                or timestamp(record["session_close_utc"]) != timestamp(metadata["next_close_utc"])
                or not timestamp(record["authorized_at_utc"]) < timestamp(record["deadline_utc"]) <= timestamp(record["session_close_utc"])
                or (timestamp(record["deadline_utc"])-timestamp(record["authorized_at_utc"])).total_seconds() > 600):
            raise ValueError("NATIVE_MANUAL_PERMISSION_BINDING_CHANGED")
        continuation = record.get("request", {}).get("continuation")
        if continuation is not None:
            rows = self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
                "AND json_extract(detail,'$.request.manual_id')=? LIMIT 2", (record.get("prior_manual_id"),)).fetchall()
            prior = json.loads(rows[0][0]) if len(rows) == 1 else None
            bound = ("strategy_id", "account_id", "budget", "unused_cash", "signal_date", "execution_date", "plan_sha256",
                "metadata_sha256", "source_archive", "source_refs_sha256", "reset_receipt_sha256", "bootstrap_sha256",
                "next_open_utc", "signal_close_utc", "session_close_utc", "ordinary_execution_clock")
            if (not isinstance(continuation, dict) or set(continuation) != {"expected_prior_sha256", "expected_execution_sha256"}
                    or not prior or prior.get("schema") != record["schema"] or prior.get("manual_id") != record.get("prior_manual_id")
                    or prior.get("manual_id") == record["manual_id"] or any(prior.get(k) != record.get(k) for k in bound)
                    or self._content_sha(prior) != record.get("prior_manual_sha256")
                    or record["prior_manual_sha256"] != continuation["expected_prior_sha256"]
                    or record["original_execution_sha256"] != continuation["expected_execution_sha256"]
                    or timestamp(prior["deadline_utc"]) > timestamp(record["authorized_at_utc"])):
                raise ValueError("NATIVE_MANUAL_CONTINUATION_HISTORY_CHANGED")
        return record

    def authorize_native_manual_completion(self, *, manual_id, requested_at, deadline_utc, expected_strategy_id,
            signal_date, expected_plan_sha256, expected_source_sha256, expected_reset_receipt_sha256,
            expected_precondition_sha256, continuation=None, now=None):
        """Seal one explicit first/residual window; never start, alter a phase or renew automatically."""
        clock = now or self._now()
        request = dict(manual_id=manual_id, requested_at=requested_at, deadline_utc=deadline_utc,
            expected_strategy_id=expected_strategy_id, signal_date=signal_date, expected_plan_sha256=expected_plan_sha256,
            expected_source_sha256=expected_source_sha256, expected_reset_receipt_sha256=expected_reset_receipt_sha256,
            expected_precondition_sha256=expected_precondition_sha256)
        if (not isinstance(clock, datetime) or clock.tzinfo is None
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(manual_id))
                or expected_strategy_id != self.strategy_id
                or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in
                    (expected_plan_sha256, expected_source_sha256, expected_reset_receipt_sha256, expected_precondition_sha256))):
            raise ValueError("NATIVE_MANUAL_REQUEST_INVALID")
        if continuation is not None:
            if (not isinstance(continuation, dict) or set(continuation) != {"expected_prior_sha256", "expected_execution_sha256"}
                    or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in continuation.values())):
                raise ValueError("NATIVE_MANUAL_CONTINUATION_REQUEST_INVALID")
            request["continuation"] = deepcopy(continuation)
        owner = getattr(self, "_maintenance_owner", None)
        with (owner.lock if owner is not None else nullcontext()), self.lock, self.engine.lock:
            prior = self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
                "AND json_extract(detail,'$.request.manual_id')=? LIMIT 2", (manual_id,)).fetchall()
            if prior:
                record = self._verified_manual_completion_record()
                if len(prior) != 1 or json.loads(prior[0][0]).get("request") != request or record != json.loads(prior[0][0]):
                    raise ValueError("NATIVE_MANUAL_ID_REUSED_OR_SUPERSEDED")
                saved = self.engine._get("best_plan", {})
                self._native_manual_record(record, saved.get("plan"), saved.get("metadata", {}))
                return dict(self._manual_completion_summary(), idempotent=True, orders_created=0, running=not self.stop_event.is_set())
            self._native_reset_require_idle(owner)
            self._require_manual_preparation()
            if not clock-timedelta(seconds=60) <= timestamp(requested_at) <= clock:
                raise ValueError("NATIVE_MANUAL_FRESH_REQUEST_REQUIRED")
            saved = self.engine._get("best_plan", {})
            plan, frozen = saved.get("plan"), saved.get("metadata", {})
            epoch, bootstrap = self._native_manual_binding(plan, frozen, clock=clock, source=True)
            ordinary = self._native_manual_clock(frozen)
            opening, closing, deadline = tuple(timestamp(frozen[k]) for k in ("next_open_utc", "next_close_utc")) + (timestamp(deadline_utc),)
            ny = ZoneInfo("America/New_York")
            if (signal_date != frozen.get("signal_date") or not signal_date < frozen["execution_date"]
                    or clock.astimezone(ny).date().isoformat() != frozen["execution_date"]
                    or closing.astimezone(ny).date().isoformat() != frozen["execution_date"]
                    or not timestamp(ordinary["execution_time_utc"])+timedelta(seconds=ordinary["execution_window_seconds"]) <= clock < deadline <= min(clock+timedelta(seconds=600), closing)
                    or expected_plan_sha256 != self._content_sha(plan) or expected_source_sha256 != frozen["archive"]["sha256"]
                    or expected_reset_receipt_sha256 != self._content_sha(epoch)
                    or expected_precondition_sha256 != self._target_alignment_precondition()
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("quotes") != {}
                    or self.snapshot.get("open_orders") != [] or not 0 <= time.monotonic()-self.last_snapshot_at <= 60
                    or any(type(self.snapshot.get(k)) not in (int, float) or not math.isfinite(self.snapshot[k]) or self.snapshot[k] < 0
                        for k in ("cash", "equity")) or self.snapshot["equity"] <= 0):
                raise ValueError("NATIVE_MANUAL_CURRENT_TARGET_OR_WINDOW_CHANGED")
            execution = self.engine._get("best_execution", {})
            previous = None
            if continuation is None:
                if (execution.get("signal_date") == signal_date
                        or self.engine.db.execute("SELECT 1 FROM orders WHERE mode='moomoo_simulate' AND account_id=? "
                            "AND julianday(created_at)>=julianday(?) LIMIT 1", (epoch["new_account_id"], opening.isoformat())).fetchone()
                        or self.engine.db.execute("SELECT 1 FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
                            "AND json_extract(detail,'$.schema')='OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1' "
                            "AND json_extract(detail,'$.signal_date')=? LIMIT 1", (signal_date,)).fetchone()):
                    raise ValueError("NATIVE_MANUAL_UNSTARTED_ONCE_ONLY")
            else:
                previous = self._manual_completion_record(plan, frozen)
                if (not previous or previous.get("schema") != "OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1"
                        or previous.get("manual_id") == manual_id or self._content_sha(previous) != continuation["expected_prior_sha256"]
                        or clock < timestamp(previous["deadline_utc"]) or execution.get("signal_date") != signal_date
                        or execution.get("phase") not in {"SELL", "BUY"}
                        or self._content_sha(execution) != continuation["expected_execution_sha256"]
                        or execution.get("original_target_weights") != {row["code"]:row["target_weight"] for row in plan["rows"]}
                        or execution.get("original_target_cash_weight") != plan["target_cash_weight"]):
                    raise ValueError("NATIVE_MANUAL_CONTINUATION_EXPIRED_UNFINISHED_STATE_REQUIRED")
                manifest = execution.get("manifest")
                if manifest is not None:
                    try: origin = json.loads(manifest.get("source", "{}"))
                    except (TypeError, ValueError): origin = {}
                    if (not isinstance(origin, dict) or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                            or origin.get("manual_id") != previous["manual_id"] or origin.get("budget") != self.budget
                            or origin.get("execution_delay_minutes") != ordinary["execution_delay_minutes"] or origin.get("execution_window_seconds") != ordinary["execution_window_seconds"]
                            or previous.get("ordinary_execution_clock") is not None and origin.get("execution_time_utc") != ordinary["execution_time_utc"]
                            or origin.get("source_hash") != (plan.get("source_hash") or hashlib.sha256(json.dumps(plan["source_refs"], sort_keys=True).encode()).hexdigest())
                            or origin.get("published_target_manual_completion_sha256") != self._content_sha(previous)
                            or manifest.get("strategy_id") != self.strategy_id
                            or timestamp(manifest["expires_at"]) != timestamp(previous["deadline_utc"])
                            or origin.get("signal_date") != signal_date or origin.get("phase") != execution["phase"]):
                        raise ValueError("NATIVE_MANUAL_CONTINUATION_ORIGINAL_MANIFEST_CHANGED")
            fresh = self._now()
            if fresh < clock or fresh >= deadline or time.monotonic()-self.last_snapshot_at > 60:
                raise ValueError("NATIVE_MANUAL_EXPIRED_DURING_VALIDATION")
            record = dict(schema="OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1", request=request, manual_id=manual_id,
                strategy_id=self.strategy_id, account_id=epoch["new_account_id"], budget=self.budget,
                unused_cash=self.engine._get("best_capital", {})["unused_cash"], signal_date=signal_date,
                execution_date=frozen["execution_date"], next_open_utc=frozen["next_open_utc"], signal_close_utc=frozen["signal_close_utc"],
                authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(), session_close_utc=closing.isoformat(),
                plan_sha256=expected_plan_sha256, metadata_sha256=self._content_sha(frozen), source_archive=frozen["archive"],
                source_refs_sha256=self._content_sha(plan["source_refs"]), reset_receipt_sha256=expected_reset_receipt_sha256,
                bootstrap_sha256=self._content_sha(bootstrap), original_execution_sha256=self._content_sha(execution))
            if self.execution_delay_minutes != 0:
                record["ordinary_execution_clock"] = ordinary
            if previous is not None:
                record.update(prior_manual_id=previous["manual_id"], prior_manual_sha256=self._content_sha(previous))
            with self.engine.db:
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_published_target_manual_completion", json.dumps(record, ensure_ascii=False, allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(), "PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED", json.dumps(record, ensure_ascii=False, allow_nan=False)))
            return dict(self._manual_completion_summary(), idempotent=False, orders_created=0, running=False)

    def _manual_completion_record(self, plan=None, metadata=None):
        record = self._verified_manual_completion_record()
        if record is None:
            return None
        saved = self.engine._get("best_plan", {})
        plan = self.plan if plan is None else plan
        metadata = saved.get("metadata", {}) if metadata is None else metadata
        if not plan or record.get("signal_date") != metadata.get("signal_date"):
            return None  # An old grant cannot authorize a successor signal.
        if record.get("schema") == "OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1":
            return self._native_manual_record(record, plan, metadata)
        receipt = self._aligned_target_receipt(plan, metadata)
        capital, account = self.engine._get("best_capital", {}), self.engine._get("best_account", None)
        if (record.get("schema") != "OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1"
                or record.get("strategy_id") != self.strategy_id or record.get("account_id") != account
                or self.engine.mode != "moomoo_simulate" or self.engine.account_id != account
                or self.engine.broker is None or str(self.engine.broker.account_id) != account
                or capital.get("account_id") != account or record.get("budget") != self.budget
                or capital.get("budget") != self.budget or record.get("unused_cash") != capital.get("unused_cash")
                or record.get("plan_sha256") != self._content_sha(plan)
                or record.get("metadata_sha256") != self._content_sha(metadata)
                or record.get("alignment_receipt_sha256") != self._content_sha(receipt)
                or record.get("published_target_sha256") != plan.get("published_target_sha256")
                or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes
                or record.get("original_execution_sha256") != self._content_sha(record.get("original_execution"))
                or record.get("resumed_execution") is not None and record.get("resumed_execution_sha256") != self._content_sha(record["resumed_execution"])
                or record.get("execution_date") != metadata.get("execution_date")
                or not timestamp(record["authorized_at_utc"]) < timestamp(record["deadline_utc"]) <= timestamp(record["session_close_utc"])
                or (timestamp(record["deadline_utc"])-timestamp(record["authorized_at_utc"])).total_seconds() > 600):
            raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_BINDING_CHANGED")
        return record

    def authorize_manual_published_completion(self, *, manual_id, requested_at, deadline_utc,
            expected_strategy_id, signal_date, expected_target_sha256, expected_precondition_sha256, now=None):
        """An explicit bounded grant resumes the same differential phase; never renew automatically."""
        from .cohort import Cohort
        clock = now or self._now()
        request = dict(manual_id=manual_id, requested_at=requested_at, deadline_utc=deadline_utc,
            expected_strategy_id=expected_strategy_id, signal_date=signal_date,
            expected_target_sha256=expected_target_sha256, expected_precondition_sha256=expected_precondition_sha256)
        if (clock.tzinfo is None or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(manual_id))
                or expected_strategy_id != self.strategy_id or self.strategy_id not in ACTIVE_PAPER_STRATEGY_IDS
                or not all(re.fullmatch(r"[0-9a-f]{64}", str(v)) for v in (expected_target_sha256, expected_precondition_sha256))
                or timestamp(requested_at) > clock):
            raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_REQUEST_INVALID")
        with self.lock, self.engine.lock:
            prior = self.engine.db.execute("SELECT detail FROM audit WHERE event='PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED' "
                "AND json_extract(detail,'$.request.manual_id')=? LIMIT 2", (manual_id,)).fetchall()
            if prior:
                current = self.engine._get("best_published_target_manual_completion", None)
                if len(prior) != 1 or json.loads(prior[0][0]).get("request") != request:
                    raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_ID_REUSED")
                if current != json.loads(prior[0][0]):
                    raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_SUPERSEDED")
                saved = self.engine._get("best_plan", {})
                self._manual_completion_record(saved.get("plan"), saved.get("metadata"))
                return self.state()
            if timestamp(requested_at) < clock-timedelta(seconds=60):
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_FRESH_REQUEST_REQUIRED")
            self.engine._require_stopped()
            self._pending_repair_guard()
            capital, account = self.engine._get("best_capital", {}), self.engine._get("best_account", None)
            if (not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                    or self.engine._pending() or self.engine.halt_event.is_set()
                    or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                    or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                    or capital.get("account_id") != account or capital.get("budget") != self.budget
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                    or time.monotonic()-self.last_snapshot_at > 60
                    or self._target_alignment_precondition() != expected_precondition_sha256):
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_REQUIRES_STOPPED_FRESH_RECONCILE")
            saved = self.engine._get("best_plan", {})
            plan, frozen = saved.get("plan", {}), saved.get("metadata", {})
            receipt = self._aligned_target_receipt(plan, frozen)
            previous = self._manual_completion_record(plan, frozen)
            if previous and clock < timestamp(previous["deadline_utc"]):
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_WINDOW_ALREADY_ACTIVE")
            current = Cohort._book_source_data(self.strategy_id, self.source.status(now=clock))
            self._published_target_binding(plan, frozen, current)
            close, opening, deadline = timestamp(current["next_close_utc"]), timestamp(frozen["next_open_utc"]), timestamp(deadline_utc)
            if (signal_date != frozen.get("signal_date") or expected_target_sha256 != plan.get("published_target_sha256")
                    or clock.astimezone(ZoneInfo("America/New_York")).date().isoformat() != frozen.get("execution_date")
                    or close.astimezone(ZoneInfo("America/New_York")).date().isoformat() != frozen.get("execution_date")
                    or not opening <= clock < deadline <= min(clock+timedelta(seconds=600),close)
                    or frozen.get("next_close_utc") is not None and timestamp(frozen["next_close_utc"]) != close
                    or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes
                    or self._target_alignment_precondition() != expected_precondition_sha256):
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_TARGET_OR_WINDOW_CHANGED")
            execution = self.engine._get("best_execution", {})
            resume = None
            if execution.get("signal_date") != signal_date:
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_UNFINISHED_PHASE_REQUIRED")
            if execution.get("phase") == "DONE" and execution.get("completion_status") == "PARTIALLY_EXECUTED":
                weights = {row["code"]:row["target_weight"] for row in plan["rows"]}
                quantities = execution.get("target_quantities", {})
                positions = self.snapshot.get("positions", {})
                outside = [code for code,p in positions.items() if p.get("qty",0)>0 and not weights.get(code,0)]
                unresolved = [code for code,w in weights.items() if w>0 and (
                    code not in quantities or quantities[code]!=positions.get(code,{}).get("qty",0))]
                if not outside and not unresolved:
                    raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_NO_REMAINING_DIFFERENCE")
                resume = deepcopy(execution)
                resume.update(phase="BUY")
                resume.pop("completion_status",None)
                deferred = {row["code"]:row for row in resume.get("deferred_sells",[])}
                for code in outside:
                    deferred.setdefault(code,dict(code=code,reason="已审计发布目标仍有退出差额"))
                resume["deferred_sells"] = list(deferred.values())
                # Preserve filled-code/idempotency state. Only unresolved codes may be rebuilt.
                remaining = set(outside+unresolved)
                resume["processed_codes"] = [code for code in resume.get("processed_codes",[]) if code not in remaining]
            elif execution.get("phase") not in {"SELL", "BUY"}:
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_UNFINISHED_PHASE_REQUIRED")
            record = dict(schema="OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1", request=request,
                manual_id=manual_id, authorized_at_utc=clock.isoformat(), deadline_utc=deadline.isoformat(),
                session_close_utc=close.isoformat(), strategy_id=self.strategy_id, signal_date=signal_date,
                execution_date=frozen["execution_date"], account_id=account, budget=self.budget,
                unused_cash=capital["unused_cash"], plan_sha256=self._content_sha(plan), metadata_sha256=self._content_sha(frozen),
                published_target_sha256=expected_target_sha256, alignment_id=plan["published_target_alignment_id"],
                alignment_receipt_sha256=self._content_sha(receipt), source_refs_sha256=self._content_sha(plan["source_refs"]),
                original_execution=deepcopy(execution), original_execution_sha256=self._content_sha(execution),
                previous_manual_receipt_sha256=self._content_sha(previous) if previous else None)
            if resume is not None:
                record.update(resumed_execution=deepcopy(resume),resumed_execution_sha256=self._content_sha(resume))
            with self.engine.db:
                if resume is not None:
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("best_execution",json.dumps(resume,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_published_target_manual_completion", json.dumps(record,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(),"PUBLISHED_TARGET_MANUAL_COMPLETION_AUTHORIZED",json.dumps(record,ensure_ascii=False,allow_nan=False)))
            return self.state()

    def _manual_manifest_guard(self, manifest, clock):
        try:
            origin = json.loads(manifest.get("source", "{}"))
        except (TypeError,ValueError):
            origin = {}
        if not isinstance(origin,dict):
            origin = {}
        record = self._manual_completion_record()
        if record is not None and record.get("schema") == "OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1":
            saved = self.engine._get("best_plan", {})
            self._native_manual_binding(saved.get("plan"), saved.get("metadata", {}), clock=clock, source=True)
            ordinary = self._native_manual_clock(saved.get("metadata", {}), record=record)
            state = self.engine._get("best_execution", {})
            if (origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN" or origin.get("phase") not in {"SELL", "BUY"}
                    or origin.get("budget") != self.budget or origin.get("execution_delay_minutes") != ordinary["execution_delay_minutes"]
                    or record.get("ordinary_execution_clock") is not None and origin.get("execution_time_utc") != ordinary["execution_time_utc"]
                    or origin.get("execution_window_seconds") != ordinary["execution_window_seconds"]
                    or any(origin.get(k) != record.get(k) for k in ("next_open_utc", "signal_close_utc"))
                    or origin.get("native_first_execution_permission_sha256") is not None
                    or origin.get("first_execution_permission_sha256") is not None
                    or state.get("signal_date") != record["signal_date"] or state.get("manifest") != manifest
                    or state.get("phase") != origin.get("phase")):
                raise ValueError("NATIVE_MANUAL_MANIFEST_CHANGED")
        marked = origin.get("published_target_manual_completion_sha256")
        if marked is None:
            if (record is not None and origin.get("kind")=="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                    and origin.get("signal_date")==record["signal_date"]
                    and clock>=timestamp(self.metadata["next_open_utc"])+timedelta(seconds=self.execution_window_seconds)):
                raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_MANIFEST_PERMISSION_REQUIRED")
            return None
        if (record is None or marked != self._content_sha(record)
                or origin.get("manual_id") != record["manual_id"] or origin.get("signal_date") != record["signal_date"]
                or manifest.get("strategy_id") != record["strategy_id"] or timestamp(manifest["expires_at"]) != timestamp(record["deadline_utc"])
                or origin.get("source_hash") != (self.plan.get("source_hash") or hashlib.sha256(json.dumps(self.plan["source_refs"],sort_keys=True).encode()).hexdigest())
                or not timestamp(record["authorized_at_utc"]) <= clock < timestamp(record["deadline_utc"])
                or clock.astimezone(ZoneInfo("America/New_York")).date().isoformat() != record["execution_date"]):
            raise ValueError("PUBLISHED_TARGET_MANUAL_COMPLETION_MANIFEST_CHANGED_OR_EXPIRED")
        return record

    def _completed_manual_history(self, record):
        """Read an audited completed conversion; never confer a send permission."""
        try:
            completed = self.engine._get("best_published_target_conversion", None)
            if (not isinstance(completed, dict) or completed.get("schema") != "OWNER_PUBLISHED_TARGET_CONVERSION_R1"
                    or completed.get("status") != "COMPLETED"):
                return False
            self._target_conversion()  # Original audit/identity guard; COMPLETED intentionally returns None.
            if (self.engine._get("best_published_target_conversion", None) != completed
                    or self._verified_manual_completion_record() != record):
                return False
            alignment = self._alignment_record(completed["last_alignment_id"])
            if (record.get("schema") != "OWNER_PUBLISHED_TARGET_MANUAL_COMPLETION_R1"
                    or record.get("strategy_id") != self.strategy_id or completed.get("strategy_id") != self.strategy_id
                    or record.get("account_id") != completed["account_id"]
                    or record.get("budget") != completed["budget"] or record.get("budget") != self.budget
                    or record.get("alignment_id") != completed["last_alignment_id"]
                    or record.get("alignment_receipt_sha256") != completed["last_alignment_sha256"]
                    or record.get("published_target_sha256") != completed["last_published_target_sha256"]
                    or record.get("signal_date") != completed["last_signal_date"]
                    or record.get("execution_date") != completed["last_execution_date"]
                    or record.get("plan_sha256") != alignment.get("plan_sha256")
                    or record.get("metadata_sha256") != alignment.get("metadata_sha256")):
                return False
            for value in (completed.get("last_alignment_sha256"), completed.get("last_published_target_sha256"),
                          completed.get("completed_execution_sha256"), completed.get("reconciled_positions_sha256"),
                          record.get("plan_sha256"), record.get("metadata_sha256")):
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    return False
            signal, execution = record["signal_date"], record["execution_date"]
            for day in (signal, execution):
                if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                    return False
                datetime.fromisoformat(day)  # Strict civil date; original grants already bind the calendar.
            authorized, deadline, close = (timestamp(record[key]) for key in
                                          ("authorized_at_utc", "deadline_utc", "session_close_utc"))
            done = timestamp(completed["completed_at"])
            ny = ZoneInfo("America/New_York")
            return (signal < execution and authorized < deadline <= close
                and (deadline - authorized).total_seconds() <= 600
                and all(value.astimezone(ny).date().isoformat() == execution for value in (authorized, deadline, close))
                and authorized <= done <= self._now() and timestamp(completed["updated_at"]) == done)
        except (ValueError, KeyError, TypeError, AttributeError):
            return False

    def _manual_completion_summary(self):
        record = self.engine._get("best_published_target_manual_completion", None)
        if not record: return None
        fields = {"schema","manual_id","authorized_at_utc","deadline_utc","session_close_utc","strategy_id",
            "signal_date","execution_date","published_target_sha256","alignment_id","plan_sha256"}
        result = {k:v for k,v in record.items() if k in fields}
        execution = self.engine._get("best_execution", {})
        current_done = (execution.get("signal_date")==record["signal_date"] and execution.get("phase")=="DONE"
            and execution.get("completion_status")=="EXECUTED")
        result["status"] = ("COMPLETED" if current_done or self._completed_manual_history(record)
            else "EXPIRED" if self._now()>=timestamp(record["deadline_utc"]) else "ACTIVE")
        result["receipt_sha256"] = self._content_sha(record)
        return result

    def _continue_target_conversion(self, state, metadata, now, *, prepare_only=False):
        target = self.published_target_provider(self.strategy_id, metadata["signal_date"]) if callable(self.published_target_provider) else None
        if target is None:
            self.plan = None
            self.status, self.reason = "WAITING_SOURCE", "统一持仓尚未完成；等待本期已冻结发布目标，不改用旧仓HOLD计划"
            return
        plan, frozen = target["plan"], target["metadata"]
        if self.strategy_id == "R7_GROSS_LINEAR":
            requested = self.engine._get("best_requested_strategy_state", {}).get(self.strategy_id, {})
            if abs(number(plan.get("previous_requested_gross"), "发布目标前期请求G") - requested_gross_input(requested, metadata["signal_date"])) > 1e-12:
                raise ValueError("PUBLISHED_TARGET_CONVERSION_REQUESTED_G_INPUT_CHANGED")
        if prepare_only:
            self._require_manual_preparation()
        else:
            self._require_running()
        self._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
        digest = self._content_sha(plan)
        ident = "continue_" + self._content_sha([state["conversion_id"], metadata["signal_date"], digest])[:48]
        self._align_published_target(alignment_id=ident, requested_at=now.isoformat(), expected_strategy_id=self.strategy_id,
            signal_date=metadata["signal_date"], expected_target_sha256=digest,
            expected_precondition_sha256=self._target_alignment_precondition(), published_plan=plan, published_metadata=frozen,
            now=now, conversion=state, prepare_only=prepare_only)
        self.metadata.update({key: metadata[key] for key in ("status", "reason", "ready", "execute_now", "next_expected_open_utc") if key in metadata})

    def _complete_target_conversion(self, now, *, in_transaction=False):
        state = self._target_conversion()
        if state is None: return
        execution = self.engine._get("best_execution", {})
        if (execution.get("signal_date") != state["last_signal_date"] or execution.get("phase") != "DONE"
                or execution.get("completion_status") != "EXECUTED" or self.engine._pending()): return
        saved = self.engine._get("best_plan", {})
        self._aligned_target_receipt(saved["plan"], saved["metadata"])
        positive = {row["code"] for row in saved["plan"]["rows"] if row["target_weight"] > 0}
        if any(value.get("qty", 0) > 0 and code not in positive for code, value in self.snapshot.get("positions", {}).items()): return
        finished = dict(state, status="COMPLETED", completed_at=now.isoformat(), updated_at=now.isoformat(), completed_execution_sha256=self._content_sha(execution),
            reconciled_positions_sha256=self._content_sha({code:value["qty"] for code,value in self.snapshot.get("positions",{}).items()}))
        def persist():
            self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_published_target_conversion", json.dumps(finished, ensure_ascii=False, allow_nan=False)))
            self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(), "PUBLISHED_TARGET_CONVERSION_STATE", json.dumps(finished, ensure_ascii=False, allow_nan=False)))
        if in_transaction:
            persist()
        else:
            with self.engine.db:
                persist()

    def _acknowledge_resolved_target_completion(self, now):
        """A late terminal receipt can close an already fulfilled target, without send authority."""
        from .cohort import Cohort
        raw_execution_row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_execution'").fetchone()
        execution = json.loads(raw_execution_row[0]) if raw_execution_row else {}
        if execution.get("phase") == "DONE":
            self._complete_target_conversion(now)
            return False
        if (execution.get("phase") != "BUY" or execution.get("skipped") or execution.get("deferred_sells")
                or not self.stop_event.is_set() or self.worker and self.worker.is_alive()
                or self.engine._pending() or self.engine.halt_event.is_set()
                or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                or time.monotonic()-self.last_snapshot_at > 60):
            return False
        raw_plan_row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()
        saved = json.loads(raw_plan_row[0]) if raw_plan_row else {}
        plan, frozen = saved.get("plan", {}), saved.get("metadata", {})
        if (plan.get("published_target_alignment_id") is None
                or execution.get("signal_date") != frozen.get("signal_date")
                or now.astimezone(ZoneInfo("America/New_York")).date().isoformat() != frozen.get("execution_date")):
            return False
        receipt = self._aligned_target_receipt(plan,frozen)
        weights = {row["code"]:row["target_weight"] for row in plan["rows"]}
        positive = {code for code,w in weights.items() if w>0}
        quantities = execution.get("target_quantities",{})
        positions = {code:item["qty"] for code,item in self.snapshot["positions"].items() if item["qty"]>0}
        if (not positive or not positive.issubset(quantities)
                or any(type(q) is not int or q<0 for q in quantities.values())
                or any(positions.get(code,0)!=quantities[code] for code in positive)
                or any(code not in positive for code in positions)):
            return False
        manifest = execution.get("manifest")
        if not isinstance(manifest,dict):
            return False
        try:
            origin = json.loads(manifest.get("source", ""))
        except (TypeError,ValueError):
            return False
        source_hash = plan.get("source_hash") or hashlib.sha256(json.dumps(plan["source_refs"],sort_keys=True).encode()).hexdigest()
        if (not isinstance(origin,dict) or origin.get("kind")!="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or origin.get("phase")!="BUY" or origin.get("signal_date")!=frozen["signal_date"]
                or manifest.get("strategy_id")!=self.strategy_id or origin.get("source_hash")!=source_hash):
            raise ValueError("PUBLISHED_TARGET_COMPLETION_MANIFEST_BINDING_CHANGED")
        if origin.get("published_target_manual_completion_sha256") is not None:
            manual = self._manual_completion_record(plan,frozen)
            if (manual is None or origin["published_target_manual_completion_sha256"]!=self._content_sha(manual)
                    or origin.get("manual_id")!=manual["manual_id"]
                    or timestamp(manifest["expires_at"])!=timestamp(manual["deadline_utc"])):
                raise ValueError("PUBLISHED_TARGET_COMPLETION_MANUAL_RECEIPT_CHANGED")
            permitted_start = timestamp(manual["authorized_at_utc"])
        else:
            if timestamp(manifest["expires_at"])!=timestamp(frozen["next_open_utc"])+timedelta(seconds=self.execution_window_seconds):
                raise ValueError("PUBLISHED_TARGET_COMPLETION_ORDINARY_DEADLINE_CHANGED")
            permitted_start = timestamp(frozen["next_open_utc"])
        account = self.engine._get("best_account", None)
        last = self.engine.db.execute("SELECT o.created_at,o.qty,o.order_id,f.payload FROM orders o JOIN order_fills f ON f.id=o.id "
            "WHERE o.mode='moomoo_simulate' AND o.account_id=? AND o.strategy_id=? AND o.side='BUY' "
            "AND o.status IN ('FILLED_ALL','FILLED') AND julianday(o.created_at)>=julianday(?) "
            "ORDER BY julianday(o.created_at) DESC,o.id DESC LIMIT 1",(account,self.strategy_id,frozen["next_open_utc"])).fetchone()
        if not last:
            return False
        fill = json.loads(last["payload"])
        if (not last["order_id"] or type(fill.get("fill_qty")) is not int or fill["fill_qty"]!=last["qty"]
                or fill.get("fill_source")!="MOOMOO_SIMULATE_ORDER_RECONCILE"
                or not permitted_start <= timestamp(last["created_at"]) < timestamp(manifest["expires_at"])):
            return False
        current = Cohort._book_source_data(self.strategy_id,self.source.status(now=now))
        self._published_target_binding(plan,frozen,current)
        closed = dict(execution,phase="DONE",completion_status="EXECUTED",
            completion_acknowledged_at_utc=now.isoformat(),completion_basis="FRESH_RECONCILED_RESOLVED_INTEGER_TARGETS")
        proof = dict(schema="PUBLISHED_TARGET_COMPLETION_ACKNOWLEDGEMENT_R1",acknowledged_at_utc=now.isoformat(),
            signal_date=frozen["signal_date"],execution_date=frozen["execution_date"],strategy_id=self.strategy_id,
            account_id=account,budget=self.budget,alignment_id=plan["published_target_alignment_id"],
            alignment_receipt_sha256=self._content_sha(receipt),published_target_sha256=plan["published_target_sha256"],
            plan_sha256=self._content_sha(plan),metadata_sha256=self._content_sha(frozen),
            previous_execution_sha256=self._content_sha(execution),completed_execution_sha256=self._content_sha(closed),
            resolved_quantities_sha256=self._content_sha(quantities),reconciled_positions_sha256=self._content_sha(positions),
            source_refs_sha256=self._content_sha(plan["source_refs"]),orders_created=0)
        with self.engine.lock, self.engine.db:
            changed = self.engine.db.execute("UPDATE settings SET value=? WHERE key='best_execution' AND value=? "
                "AND EXISTS(SELECT 1 FROM settings WHERE key='best_plan' AND value=?)",
                (json.dumps(closed,ensure_ascii=False,allow_nan=False),raw_execution_row[0],raw_plan_row[0])).rowcount
            if changed!=1:
                raise ValueError("PUBLISHED_TARGET_COMPLETION_CAS_CHANGED")
            self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(now.isoformat(),"PUBLISHED_TARGET_COMPLETION_ACKNOWLEDGED",json.dumps(proof,ensure_ascii=False,allow_nan=False)))
            self._complete_target_conversion(now,in_transaction=True)
        return True

    def _alignment_account_guard(self, signal_close, *, conversion=None, prepare_only=False):
        if conversion is None:
            if not self.stop_event.is_set() or self.worker and self.worker.is_alive():
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_REQUIRES_STOPPED")
        elif self._target_conversion() != conversion:
            raise ValueError("PUBLISHED_TARGET_CONVERSION_AUTHORITY_CHANGED")
        else:
            if prepare_only:
                self._require_manual_preparation()
            else:
                self._require_running()
        self.engine._require_stopped()
        self._pending_repair_guard()
        account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
        if (self.engine._pending() or self.engine.halt_event.is_set()
                or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                or capital.get("account_id") != account or capital.get("budget") != self.budget
                or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                or time.monotonic() - self.last_snapshot_at > 60):
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_REQUIRES_FRESH_RECONCILED_SIM")
        count = self.engine.db.execute("SELECT COUNT(*) FROM orders o WHERE o.mode='moomoo_simulate' "
            "AND o.account_id=? AND julianday(o.created_at)>=julianday(?) AND NOT (o.status='CANCELLED_BEFORE_SEND' "
            "AND o.order_id IS NULL AND NOT EXISTS(SELECT 1 FROM order_fills f WHERE f.id=o.id))",
            (account, signal_close.isoformat())).fetchone()[0]
        if count:
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_SIGNAL_ORDER_SUBMITTED")
        return account, capital

    def _aligned_target_receipt(self, plan, frozen):
        alignment_id = plan.get("published_target_alignment_id")
        record = self.engine._get("best_published_target_alignment", None)
        account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
        if (not isinstance(record, dict) or record != self._alignment_record(alignment_id)
                or record.get("request", {}).get("alignment_id") != alignment_id
                or record.get("strategy_id") != self.strategy_id or self.strategy_id not in ACTIVE_PAPER_STRATEGY_IDS
                or record.get("account_id") != account or capital.get("account_id") != account
                or record.get("budget") != self.budget or capital.get("budget") != self.budget
                or record.get("unused_cash") != capital.get("unused_cash")
                or self.engine.mode != "moomoo_simulate" or self.engine.account_id != account
                or plan.get("execution_mode") != "REBALANCE_EXISTING_POSITIONS"
                or frozen.get("execution_mode") != "REBALANCE_EXISTING_POSITIONS"
                or plan.get("account_basis") != "USER_REQUESTED_PUBLISHED_TARGET_REBALANCE"
                or plan.get("target_origin_account_basis") != "OWNER_FROZEN_CURRENT_PLAN"
                or plan.get("valuation_basis") != "SIGNAL_CLOSE"
                or frozen.get("published_target_alignment_id") != alignment_id
                or record.get("signal_date") != plan.get("signal_date") or record.get("signal_date") != frozen.get("signal_date")
                or record.get("execution_date") != plan.get("execution_date") or record.get("execution_date") != frozen.get("execution_date")
                or record.get("plan_sha256") != self._content_sha(plan)
                or record.get("metadata_sha256") != self._content_sha(frozen)
                or record.get("preserved_settings_sha256") != self._content_sha(record.get("preserved_settings"))):
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_AUTHORIZATION_CHANGED")
        return record

    def align_published_target(self, **request):
        """Explicit current target starts a reusable conversion until reconciled."""
        return self._align_published_target(**request, conversion=None)

    def _align_published_target(self, *, alignment_id, requested_at, expected_strategy_id, signal_date,
            expected_target_sha256, expected_precondition_sha256, published_plan, published_metadata, now=None, conversion=None, prepare_only=False):
        """One guarded differential builder for explicit and authorized successor targets."""
        from .cohort import Cohort
        clock = timestamp((now or self._now()).isoformat())
        request = dict(alignment_id=alignment_id, requested_at=requested_at,
            expected_strategy_id=expected_strategy_id, signal_date=signal_date,
            expected_target_sha256=expected_target_sha256, expected_precondition_sha256=expected_precondition_sha256)
        if (not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", str(alignment_id))
                or expected_strategy_id != self.strategy_id or self.strategy_id not in ACTIVE_PAPER_STRATEGY_IDS
                or not all(re.fullmatch(r"[0-9a-f]{64}", str(value)) for value in (expected_target_sha256, expected_precondition_sha256))
                or timestamp(requested_at) > clock):
            raise ValueError("PUBLISHED_TARGET_ALIGNMENT_REQUEST_INVALID")
        with self.lock, self.engine.lock:
            previous = self._alignment_record(alignment_id)
            if previous:
                if previous.get("request") != request:
                    raise ValueError("PUBLISHED_TARGET_ALIGNMENT_ID_REUSED")
                saved = self.engine._get("best_plan", None)
                if not saved or saved.get("plan", {}).get("published_target_alignment_id") != alignment_id:
                    raise ValueError("PUBLISHED_TARGET_ALIGNMENT_SUPERSEDED")
                self._aligned_target_receipt(saved["plan"], saved["metadata"])
                return self.state()
            plan, frozen = deepcopy(published_plan), deepcopy(published_metadata)
            if (not isinstance(plan, dict) or not isinstance(frozen, dict)
                    or plan.get("strategy_id") != self.strategy_id or plan.get("status") != "READY"
                    or plan.get("signal_date") != signal_date or frozen.get("signal_date") != signal_date
                    or plan.get("execution_date") != frozen.get("execution_date")
                    or plan.get("model_fit_calls") != 0 or plan.get("data_gaps")
                    or self._content_sha(plan) != expected_target_sha256
                    or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_OWNER_TARGET_CHANGED")
            current = Cohort._book_source_data(self.strategy_id, self.source.status(now=clock))
            close, opening = timestamp(frozen["signal_close_utc"]), self._scheduled_open(frozen["next_open_utc"])
            if (not close <= timestamp(requested_at) <= clock < opening + timedelta(seconds=self.execution_window_seconds)
                    or current.get("status") not in {"READY", "OPEN_WINDOW"} or current.get("data_gaps")
                    or any(current.get(key) != frozen.get(key) for key in ("signal_date","execution_date","next_open_utc","signal_close_utc"))):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_WINDOW_OR_CLOCK_CHANGED")
            Cohort._match_source_refs(plan.get("source_refs"), current, "PUBLISHED_TARGET_ALIGNMENT_SOURCE_CHANGED")
            session_close = current.get("next_close_utc")
            if (not isinstance(session_close, str) or timestamp(session_close) <= opening
                    or timestamp(session_close).astimezone(ZoneInfo("America/New_York")).date().isoformat() != frozen["execution_date"]
                    or frozen.get("next_close_utc") is not None and timestamp(frozen["next_close_utc"]) != timestamp(session_close)):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_CURRENT_SESSION_CLOSE_REQUIRED")
            frozen["next_close_utc"] = session_close
            account, capital = self._alignment_account_guard(close, conversion=conversion, prepare_only=prepare_only)
            if self._target_alignment_precondition() != expected_precondition_sha256:
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_PRECONDITION_CHANGED")
            prior_execution = self.engine._get("best_execution", {})
            if prior_execution and (conversion is None or prior_execution.get("signal_date", signal_date) >= signal_date):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_EXECUTION_EXISTS")
            if conversion is not None and conversion["last_signal_date"] >= signal_date:
                raise ValueError("PUBLISHED_TARGET_CONVERSION_SUCCESSOR_SIGNAL_REQUIRED")
            book = self._book()
            states = self.source.close_states({self.strategy_id: book}, signal_date=signal_date)
            own = states.get(self.strategy_id, {})
            if (set(states) != {self.strategy_id} or own.get("signal_date") != signal_date
                    or own.get("valuation_basis") != "SIGNAL_CLOSE"
                    or abs(sum(number(w,"signal close weight") for w in own.get("weights", {}).values()) + number(own.get("cash_weight"),"signal close cash")-1)>1e-8):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_OWN_CLOSE_STATE_REQUIRED")
            # Recheck after read-only source work; no moving account can be rebound.
            self._alignment_account_guard(close, conversion=conversion, prepare_only=prepare_only)
            if self._target_alignment_precondition() != expected_precondition_sha256:
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_PRECONDITION_CHANGED")
            owner_rows = plan.get("rows", [])
            if (not owner_rows or len(owner_rows)>150 or any(not code_valid(row.get("code")) for row in owner_rows)
                    or len({row["code"] for row in owner_rows})!=len(owner_rows)
                    or abs(sum(number(row.get("target_weight"),"target weight") for row in owner_rows)+number(plan.get("target_cash_weight"),"target cash")-1)>1e-8
                    or any(number(row["target_weight"],"target weight")>1 for row in owner_rows)):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_TARGET_INVALID")
            rows=[]
            for row in owner_rows:
                ticker=row["code"].removeprefix("US.")
                value=deepcopy(row);value.pop("exact_hold_units",None)
                value.update(ticker=ticker,explicit_target=True,action="TARGET" if row["target_weight"]>0 else "SELL",
                    weight_before=own["weights"].get(ticker,0))
                rows.append(value)
            missing=set(book["positions"])-{row["code"] for row in rows}
            for code in sorted(missing):
                ticker=code.removeprefix("US.");security=own.get("security_ids",{}).get(ticker)
                if not security:raise ValueError("PUBLISHED_TARGET_ALIGNMENT_HELD_IDENTITY_REQUIRED:"+ticker)
                rows.append(dict(code=code,ticker=ticker,security_id=security,target_weight=0.,
                    weight_before=own["weights"].get(ticker,0),explicit_target=True,action="SELL"))
            plan.update(rows=rows,account_basis="USER_REQUESTED_PUBLISHED_TARGET_REBALANCE",valuation_basis="SIGNAL_CLOSE",
                cash_weight_before=own["cash_weight"],target_origin_account_basis="OWNER_FROZEN_CURRENT_PLAN",
                execution_mode="REBALANCE_EXISTING_POSITIONS",published_target_alignment_id=alignment_id,
                published_target_sha256=expected_target_sha256)
            frozen.update(source_refs=deepcopy(plan["source_refs"]),execution_mode="REBALANCE_EXISTING_POSITIONS",
                published_target_alignment_id=alignment_id,published_target_sha256=expected_target_sha256,
                execution_time_utc=opening.isoformat(),execution_delay_minutes=0,execution_window_seconds=600,allow_partial_quotes=True)
            requested=deepcopy(self.engine._get("best_requested_strategy_state",{}))
            if self.strategy_id=="R7_GROSS_LINEAR":
                requested[self.strategy_id]=accepted_requested_gross_state(published_plan,
                    {"previous_requested_gross":published_plan.get("previous_requested_gross")},signal_date)
            own["units"]={code.removeprefix("US."):qty for code,qty in book["positions"].items()}
            preserved={key:raw for key,raw in self.engine.db.execute("SELECT key,value FROM settings")
                if key in {"best_plan","best_execution","best_requested_strategy_state","active","best_last_error","best_published_target_conversion"}}
            prior_record=self.engine._get("best_published_target_alignment",None)
            record=dict(schema="PUBLISHED_TARGET_ALIGNMENT_R1",request=request,strategy_id=self.strategy_id,
                prepared_at=clock.isoformat(),signal_date=signal_date,execution_date=frozen["execution_date"],
                account_id=account,budget=self.budget,unused_cash=capital["unused_cash"],
                published_target_sha256=expected_target_sha256,plan_sha256=self._content_sha(plan),metadata_sha256=self._content_sha(frozen),
                preserved_settings=preserved,preserved_settings_sha256=self._content_sha(preserved),
                previous_alignment_id=(prior_record or {}).get("request",{}).get("alignment_id"),
                positions_at_alignment={code:qty for code,qty in book["positions"].items()},
                own_close_state_sha256=self._content_sha(own),order_submissions=0)
            if conversion is None:
                conversion_state = self._conversion_authorization(record, alignment_id, requested_at)
                conversion_event = "PUBLISHED_TARGET_CONVERSION_AUTHORIZED"
            else:
                record["conversion_id"] = conversion["conversion_id"]
                record["previous_conversion_state_sha256"] = self._content_sha(conversion)
                conversion_state = dict(conversion, last_alignment_id=alignment_id,
                    last_alignment_sha256=self._content_sha(record), last_signal_date=signal_date,
                    last_execution_date=frozen["execution_date"],last_published_target_sha256=expected_target_sha256,updated_at=clock.isoformat())
                conversion_event = "PUBLISHED_TARGET_CONVERSION_STATE"
            with self.engine.db:
                for key,value in (("best_plan",{"plan":plan,"metadata":frozen,"close_state":own}),
                        ("best_execution",{}),("best_requested_strategy_state",requested),("active",None),
                        ("best_published_target_alignment",record),("best_last_error","")):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(key,json.dumps(value,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(clock.isoformat(),"PUBLISHED_TARGET_ALIGNED",json.dumps(record,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("best_published_target_conversion",json.dumps(conversion_state,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(clock.isoformat(),conversion_event,json.dumps(conversion_state,ensure_ascii=False,allow_nan=False)))
            self.plan,self.metadata,self.last_error=plan,frozen,""
            self.engine.active,self.engine.preview_batch=None,None
            self.prepared_at,self.prewarm_state,self._prewarm_key=0.,{},None
            self.status,self.reason=("STOPPED" if conversion is None else "WAITING_OPEN"),"按当期已发布目标继续统一持仓；在原窗口按资金和持仓差额执行"
            return self.state()

    def rollback_published_target_alignment(self, *, alignment_id, expected_precondition_sha256, now=None):
        clock=timestamp((now or self._now()).isoformat())
        with self.lock,self.engine.lock:
            record=self.engine._get("best_published_target_alignment",None)
            if (not isinstance(record,dict) or record.get("request",{}).get("alignment_id")!=alignment_id
                    or record!=self._alignment_record(alignment_id)):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_ROLLBACK_ID_CHANGED")
            saved=self.engine._get("best_plan",None)
            if not saved:raise ValueError("PUBLISHED_TARGET_ALIGNMENT_ROLLBACK_PLAN_MISSING")
            self._aligned_target_receipt(saved["plan"],saved["metadata"])
            self._alignment_account_guard(timestamp(saved["metadata"]["signal_close_utc"]))
            if self._target_alignment_precondition()!=expected_precondition_sha256 or self.engine._get("best_execution",{}):
                raise ValueError("PUBLISHED_TARGET_ALIGNMENT_ROLLBACK_PRECONDITION_CHANGED")
            preserved=record["preserved_settings"]
            prior=self._alignment_record(record["previous_alignment_id"]) if record.get("previous_alignment_id") else None
            with self.engine.db:
                for key in ("best_plan","best_execution","best_requested_strategy_state","active","best_last_error","best_published_target_conversion"):
                    if key in preserved:self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",(key,preserved[key]))
                    else:self.engine.db.execute("DELETE FROM settings WHERE key=?",(key,))
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("best_published_target_alignment",json.dumps(prior,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(clock.isoformat(),"PUBLISHED_TARGET_ALIGNMENT_ROLLED_BACK",json.dumps(dict(alignment_id=alignment_id,plan_sha256=record["plan_sha256"],preserved_settings_sha256=record["preserved_settings_sha256"]))))
            original=self.engine._get("best_plan",None) or {}
            self.plan,self.metadata=original.get("plan"),original.get("metadata",{})
            self.last_error=self.engine._get("best_last_error","")
            self.engine.active=self.engine._get("active",None);self.engine.preview_batch=None
            self.prepared_at=0.;self.status,self.reason="STOPPED","已恢复对齐前冻结计划；原账户与历史保留"
            return self.state()

    def _published_target_receipt(self, plan, frozen, *, allow_disconnected=False):
        if plan.get("published_target_alignment_id") is not None:
            return self._aligned_target_receipt(plan, frozen)
        if (plan.get("execution_mode") != "REBALANCE_EXISTING_POSITIONS"
                or frozen.get("execution_mode") != "REBALANCE_EXISTING_POSITIONS"
                or plan.get("account_basis") != "USER_REQUESTED_PUBLISHED_TARGET_REBALANCE"
                or plan.get("valuation_basis") != "PUBLISHED_TARGET_WEIGHTS"
                or plan.get("target_origin_account_basis") != "CASH_START"
                or any(key in plan or key in frozen for key in
                       ("reset_id", "reset_request", "assumed_states", "execution_condition"))):
            raise ValueError("PUBLISHED_TARGET_AUTHORIZATION_CHANGED")
        capital, account = self.engine._get("best_capital", {}), self.engine._get("best_account", None)
        connected = self.engine.mode == "moomoo_simulate" and self.engine.account_id == account
        disconnected = (allow_disconnected and self.engine.mode == "paper" and self.engine.broker is None
                        and self.engine.account_id == self.engine.paper_account_id)
        for entry in self.engine._get("best_reset_archive", {}).values():
            cancellation = entry.get("cancellation", {})
            receipt = cancellation.get("published_target_rebalance", {})
            if (cancellation.get("published_target_rebalance_revisions")
                    or any(key in receipt for key in ("original_epoch_id", "source_template_request",
                                                       "source_template_request_sha256", "source_archive"))):
                original = cancellation.get("full_liquidation_reset", {})
                template = receipt.get("source_template_request")
                if (not {"original_epoch_id", "source_template_request", "source_template_request_sha256", "source_archive"}.issubset(receipt)
                        or receipt.get("original_epoch_id") != original.get("reset_id")
                        or template != self._source_revision_request(original["request"], receipt["package_sha256"])
                        or receipt.get("source_template_request_sha256") != self._content_sha(template)
                        or receipt.get("source_archive") != frozen.get("archive")):
                    continue
            if (receipt.get("plan_sha256") == self._content_sha(plan)
                    and receipt.get("metadata_sha256") == self._content_sha(frozen)
                    and receipt.get("signal_date") == frozen.get("signal_date")
                    and receipt.get("policy_id") == plan.get("policy_id") == "HGB_TOP20_RISK_R1"
                    and receipt.get("package_sha256") == frozen.get("source_refs", {}).get("selected/package.json", {}).get("sha256")
                    and receipt.get("execution_date") == frozen.get("execution_date") == plan.get("execution_date")
                    and receipt.get("account_id") == account == capital.get("account_id")
                    and (connected or disconnected)
                    and receipt.get("unused_cash") == capital.get("unused_cash")
                    and receipt.get("budget") == self.budget == capital.get("budget")):
                return receipt
        raise ValueError("PUBLISHED_TARGET_AUTHORIZATION_CHANGED")

    @staticmethod
    def _source_revision_request(original, package_sha256):
        request = deepcopy(original)
        request.update(reset_id=original["reset_id"][:32] + "_rev_" + package_sha256[:20],
                       expected_package_sha256=package_sha256)
        return request  # Keep the original timestamp stable across an archive-created/DB-failed retry.

    @staticmethod
    def _ordinary_published_target(plan, frozen, current):
        plan, metadata = deepcopy(plan), deepcopy(frozen)
        for value in (plan, metadata):
            for key in ("reset_id", "requested_at", "reset_request", "reset_request_sha256", "assumed_states",
                        "execution_condition", "cash_weight_before"):
                value.pop(key, None)
            value.update(account_basis="USER_REQUESTED_PUBLISHED_TARGET_REBALANCE",
                valuation_basis="PUBLISHED_TARGET_WEIGHTS", target_origin_account_basis="CASH_START",
                execution_mode="REBALANCE_EXISTING_POSITIONS")
        for row in plan.get("rows", []):
            row.pop("weight_before", None)
        metadata.update({key: current[key] for key in ("status", "reason", "ready", "execute_now", "next_expected_open_utc")
                         if key in current})
        return plan, metadata

    def _new_published_target_receipt(self, clock, plan, metadata, account, capital):
        return dict(prepared_at=clock.isoformat(), execution_mode="REBALANCE_EXISTING_POSITIONS",
            signal_date=metadata["signal_date"], execution_date=metadata["execution_date"],
            policy_id=plan["policy_id"], package_sha256=metadata["source_refs"]["selected/package.json"]["sha256"],
            account_id=account, budget=self.budget, unused_cash=capital["unused_cash"], plan_sha256=self._content_sha(plan),
            metadata_sha256=self._content_sha(metadata), target_origin_account_basis="CASH_START", order_submissions=0,
            previous_last_error=self.last_error)

    def prepare_current_target_rebalance(self, reset_id, now=None):
        """Use the cancelled reset's published weights once, sized from the actual account at open."""
        self._require_legacy_strategy()
        with self.lock:
            clock = timestamp((now or self._now()).isoformat())
            if not isinstance(reset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_id):
                raise ValueError("PUBLISHED_TARGET_CANCELLED_ID_REQUIRED")
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("PUBLISHED_TARGET_REQUIRES_STOPPED_EXECUTION")
            self.engine._require_stopped()
            if self.engine._pending() or self.engine.halt_event.is_set():
                raise ValueError("PUBLISHED_TARGET_REQUIRES_RECONCILED_ACCOUNT")
            if self._scoped_legacy_setting("best_full_liquidation_reset", {}):
                raise ValueError("PUBLISHED_TARGET_REQUIRES_CANCELLED_RESET")
            archive = self.engine._get("best_reset_archive", {})
            entry = archive.get(reset_id, {})
            cancellation = entry.get("cancellation", {})
            record, target = cancellation.get("full_liquidation_reset"), cancellation.get("best_plan")
            if not isinstance(record, dict) or not isinstance(target, dict):
                raise ValueError("PUBLISHED_TARGET_CANCELLED_HISTORY_REQUIRED")
            plan, frozen = target.get("plan"), target.get("metadata")
            request = record.get("request", {})
            capital, account = self.engine._get("best_capital", {}), self.engine._get("best_account", None)
            connected = self.engine.mode == "moomoo_simulate" and self.engine.account_id == account
            disconnected = (self.engine.mode == "paper" and self.engine.broker is None
                            and self.engine.account_id == self.engine.paper_account_id)
            if (not isinstance(plan, dict) or not isinstance(frozen, dict)
                    or record.get("reset_id") != reset_id or plan.get("reset_id") != reset_id
                    or record.get("stage") != "ARMED" or record.get("post_liquidation_baseline") is not None
                    or record.get("request_sha256") != self._content_sha(request)
                    or request.get("reset_id") != reset_id or request.get("strategy_ids") != [self.strategy_id]
                    or request.get("signal_date") != record.get("signal_date")
                    or request.get("expected_policy_id") != "HGB_TOP20_RISK_R1"
                    or record.get("policy_id") != request.get("expected_policy_id")
                    or record.get("expected_package_sha256") != request.get("expected_package_sha256")
                    or plan.get("policy_id") != record.get("policy_id")
                    or plan.get("signal_date") != record.get("signal_date")
                    or frozen.get("signal_date") != record.get("signal_date")
                    or frozen.get("execution_date") != record.get("execution_date")
                    or frozen.get("reset_id") != reset_id
                    or plan.get("execution_date") != record.get("execution_date")
                    or plan.get("account_basis") != "USER_REQUESTED_POST_LIQUIDATION_CASH_START"
                    or plan.get("target_origin_account_basis") != "CASH_START"
                    or plan.get("valuation_basis") != "POST_LIQUIDATION_ASSUMPTION"
                    or plan.get("model_fit_calls", 0) != 0
                    or self._content_sha(plan) != record.get("plan_sha256")
                    or self._content_sha(frozen) != record.get("metadata_sha256")
                    or frozen.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != record.get("expected_package_sha256")
                    or capital.get("account_id") != account or account != record.get("account_id")
                    or capital.get("budget") != self.budget or record.get("budget") != self.budget
                    or capital.get("unused_cash") != record.get("unused_cash") or not (connected or disconnected)
                    or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
                raise ValueError("PUBLISHED_TARGET_FROZEN_IDENTITY_CHANGED")
            current = self.source.status(now=clock)  # Lightweight readiness/identity only, no inference or SDK.
            self._published_target_binding(plan, frozen, current)
            saved = self.engine._get("best_plan", None)
            receipt = cancellation.get("published_target_rebalance")
            if receipt:
                if (not saved or self._content_sha(saved.get("plan")) != receipt.get("plan_sha256")
                        or self._content_sha(saved.get("metadata")) != receipt.get("metadata_sha256")):
                    raise ValueError("PUBLISHED_TARGET_ALREADY_REPLACED")
                self.plan, self.metadata = saved["plan"], saved["metadata"]
                return self.state()  # Never clear an already prepared/executed ordinary batch.
            opening, close = timestamp(frozen["next_open_utc"]), timestamp(frozen["signal_close_utc"])
            if (clock < timestamp(cancellation["cancelled_at"]) or close > clock or close >= opening
                    or clock >= opening + timedelta(seconds=600)
                    or current.get("status") not in {"READY", "OPEN_WINDOW"}
                    or saved is not None or self.engine._get("best_execution", {})):
                raise ValueError("PUBLISHED_TARGET_UNEXECUTED_WINDOW_REQUIRED")
            for row in self.engine.db.execute("SELECT o.*,f.payload AS fill FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
                    "WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=?", (self.strategy_id, account)):
                unsent = row["status"] == "CANCELLED_BEFORE_SEND" and row["order_id"] is None and row["fill"] is None
                if not unsent and timestamp(row["created_at"]) >= timestamp(record["prepared_at"]):
                    raise ValueError("PUBLISHED_TARGET_SUBMITTED_ORDER_EXISTS")
            plan, metadata = self._ordinary_published_target(plan, frozen, current)
            receipt = self._new_published_target_receipt(clock, plan, metadata, account, capital)
            cancellation["published_target_rebalance"] = receipt
            with self.engine.db:
                for key, value in (("best_reset_archive", archive),
                                   ("best_plan", {"metadata": metadata, "plan": plan, "close_state": None}),
                                   ("best_execution", {}), ("best_last_error", "")):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                                           (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(),
                    "PUBLISHED_TARGET_REBALANCE_PREPARED", json.dumps(receipt, ensure_ascii=False)))
            self.plan, self.metadata, self.prepared_at = plan, metadata, time.monotonic()
            self.last_error = ""
            self.status, self.reason = "STOPPED", "已准备本期已发布 HGB 对角目标；保留现有持仓，开盘按实际账户差额调仓"
            return self.state()

    def revise_current_target_rebalance(self, reset_id, expected_package_sha256, now=None):
        """Replace only an unexecuted same-signal published target after a source revision."""
        self._require_legacy_strategy()
        with self.lock:
            clock = timestamp((now or self._now()).isoformat())
            if (not isinstance(reset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_id)
                    or not isinstance(expected_package_sha256, str)
                    or not re.fullmatch(r"[0-9a-f]{64}", expected_package_sha256)):
                raise ValueError("PUBLISHED_TARGET_REVISION_IDENTITY_REQUIRED")
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("PUBLISHED_TARGET_REVISION_REQUIRES_STOPPED_EXECUTION")
            self.engine._require_stopped()
            self.plan = None  # A failed revision must never leave an old target cached for execution.
            if self.engine._pending() or self.engine.halt_event.is_set():
                raise ValueError("PUBLISHED_TARGET_REVISION_REQUIRES_RECONCILED_ACCOUNT")
            archive = self.engine._get("best_reset_archive", {})
            cancellation = archive.get(reset_id, {}).get("cancellation", {})
            record, original = cancellation.get("full_liquidation_reset", {}), cancellation.get("best_plan", {})
            receipt, saved = cancellation.get("published_target_rebalance"), self.engine._get("best_plan", None)
            if (self._scoped_legacy_setting("best_full_liquidation_reset", {}) or not isinstance(receipt, dict)
                    or not isinstance(saved, dict) or not isinstance(record, dict) or not isinstance(original, dict)
                    or record.get("reset_id") != reset_id or record.get("stage") != "ARMED"
                    or record.get("post_liquidation_baseline") is not None
                    or record.get("request_sha256") != self._content_sha(record.get("request"))
                    or record.get("plan_sha256") != self._content_sha(original.get("plan"))
                    or record.get("metadata_sha256") != self._content_sha(original.get("metadata"))):
                raise ValueError("PUBLISHED_TARGET_REVISION_CANCELLED_HISTORY_REQUIRED")
            old_plan, frozen = saved["plan"], saved["metadata"]
            checked = self._published_target_receipt(old_plan, frozen, allow_disconnected=True)
            capital, account = self.engine._get("best_capital", {}), self.engine._get("best_account", None)
            if (checked != receipt or record.get("account_id") != account
                    or record.get("budget") != self.budget or record.get("unused_cash") != capital.get("unused_cash")
                    or frozen.get("signal_date") != record.get("signal_date")
                    or frozen.get("execution_date") != record.get("execution_date")
                    or record.get("policy_id") != "HGB_TOP20_RISK_R1"
                    or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
                raise ValueError("PUBLISHED_TARGET_REVISION_ORIGINAL_ACCOUNT_REQUIRED")
            opening, close = timestamp(frozen["next_open_utc"]), timestamp(frozen["signal_close_utc"])
            if (clock < timestamp(receipt["prepared_at"]) or clock < timestamp(cancellation["cancelled_at"])
                    or close > clock or close >= opening or clock >= opening
                    or self.engine._get("best_execution", {}) or self._scoped_legacy_setting("best_same_day_catchup", None)):
                raise ValueError("PUBLISHED_TARGET_REVISION_BEFORE_UNEXECUTED_OPEN_REQUIRED")
            for row in self.engine.db.execute("SELECT o.*,f.payload AS fill FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
                    "WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=?", (self.strategy_id, account)):
                unsent = row["status"] == "CANCELLED_BEFORE_SEND" and row["order_id"] is None and row["fill"] is None
                if not unsent and timestamp(row["created_at"]) >= timestamp(receipt["prepared_at"]):
                    raise ValueError("PUBLISHED_TARGET_REVISION_SUBMITTED_ORDER_EXISTS")
            current = self.source.status(now=clock)
            if (current.get("status") != "READY" or current.get("ready") is not True or current.get("data_gaps")
                    or current.get("source_date") != record["signal_date"]
                    or any(current.get(key) != frozen.get(key) for key in
                           ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                    or current.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                    or any(current.get("source_refs", {}).get(key) != frozen.get("source_refs", {}).get(key)
                           for key in ("frozen_calendar", "session_hours_rules"))):
                raise ValueError("PUBLISHED_TARGET_REVISION_CURRENT_SOURCE_INVALID")
            if expected_package_sha256 == receipt["package_sha256"]:
                self._published_target_binding(old_plan, frozen, current)
                self.plan, self.metadata = old_plan, frozen
                return self.state()  # Idempotent delivery cannot erase a later state or create another revision.
            request = self._source_revision_request(record["request"], expected_package_sha256)
            loaded = self.source.load(states=None, now=clock, reset_request=request)
            new_frozen = {key: value for key, value in loaded.items() if key != "plans"}
            plan = loaded.get("plans", {}).get(self.strategy_id)
            if (not isinstance(plan, dict) or plan.get("policy_id") != "HGB_TOP20_RISK_R1"
                    or plan.get("strategy_id") != self.strategy_id or plan.get("signal_date") != record["signal_date"]
                    or plan.get("execution_date") != record["execution_date"]
                    or plan.get("account_basis") != "USER_REQUESTED_POST_LIQUIDATION_CASH_START"
                    or plan.get("target_origin_account_basis") != "CASH_START"
                    or plan.get("valuation_basis") != "POST_LIQUIDATION_ASSUMPTION"
                    or plan.get("model_fit_calls", 0) != 0 or loaded.get("model_fit_calls", 0) != 0
                    or loaded.get("status") != "READY"
                    or loaded.get("ready") is not True or loaded.get("data_gaps")):
                raise ValueError("PUBLISHED_TARGET_REVISION_DIRECT_CASH_START_REQUIRED")
            self._published_target_binding(plan, new_frozen, current)
            weights = [float(row["target_weight"]) for row in plan.get("rows", [])]
            codes = [row["code"] for row in plan.get("rows", [])]
            cash = float(plan["target_cash_weight"])
            if (not weights or len(codes) != len(set(codes)) or any(not code_valid(code) for code in codes)
                    or any(not math.isfinite(weight) or not 0 <= weight <= .100001 for weight in weights)
                    or not math.isfinite(cash) or not 0 <= cash <= 1 or abs(sum(weights) + cash - 1) > 1e-7):
                raise ValueError("PUBLISHED_TARGET_REVISION_WEIGHTS_INVALID")
            plan, metadata = self._ordinary_published_target(plan, new_frozen, current)
            replacement = self._new_published_target_receipt(clock, plan, metadata, account, capital)
            replacement.update(original_epoch_id=reset_id, source_template_request=deepcopy(request),
                source_template_request_sha256=self._content_sha(request), source_archive=deepcopy(loaded.get("archive")))
            revisions = cancellation.setdefault("published_target_rebalance_revisions", [])
            revisions.append(dict(revised_at=clock.isoformat(), reason="COMPLETED_MARKET_DATA_SAME_SIGNAL_SOURCE_REVISION",
                previous_best_plan=deepcopy(saved), previous_receipt=deepcopy(receipt),
                previous_best_execution=self.engine._get("best_execution", {}),
                previous_same_day_catchup=self._scoped_legacy_setting("best_same_day_catchup", None),
                previous_subscription_prewarm=deepcopy(self.prewarm_state), previous_last_error=self.last_error,
                replacement_package_sha256=expected_package_sha256))
            cancellation["published_target_rebalance"] = replacement
            with self.engine.db:
                for key, value in (("best_reset_archive", archive),
                                   ("best_plan", {"metadata": metadata, "plan": plan, "close_state": None}),
                                   ("best_execution", {}), ("best_same_day_catchup", None),
                                   ("best_subscription_prewarm", {}), ("best_last_error", "")):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                        (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (clock.isoformat(),
                    "PUBLISHED_TARGET_REBALANCE_REVISED", json.dumps(dict(reset_id=reset_id,
                        previous_package_sha256=receipt["package_sha256"], **replacement), ensure_ascii=False)))
            self.plan, self.metadata, self.prepared_at = plan, metadata, time.monotonic()
            self.prewarm_state, self._prewarm_key, self.last_error = {}, None, ""
            self.status, self.reason = "STOPPED", "已按补齐行情更新本期 HGB 对角目标；保留现有持仓，开盘差额调仓"
            return self.state()

    def _active_full_reset(self, *, allow_disconnected=False):
        if self.strategy_id != SID or self.engine._get("best_strategy_binding", None) is not None:
            return None
        record = self._scoped_legacy_setting("best_full_liquidation_reset", None)
        if not record:
            return None
        from .applied_source import _reset_request
        try:
            request = _reset_request(record["request"], now=self._now())
            if (record["request"] != request or request["strategy_ids"] != [self.strategy_id]
                    or record.get("request_sha256") != self._content_sha(request)
                    or record.get("reset_id") != request["reset_id"]
                    or record.get("signal_date") != request["signal_date"]
                    or record.get("policy_id") != request["expected_policy_id"]
                    or record.get("expected_package_sha256") != request["expected_package_sha256"]
                    or record.get("budget") != self.budget
                    or record.get("stage") not in {"ARMED", "REBUYING", "COMPLETED"}):
                raise ValueError("RESET_RECORD_BINDING_CHANGED")
            baseline = record.get("post_liquidation_baseline")
            if record["stage"] == "ARMED":
                if baseline is not None:
                    raise ValueError("RESET_STAGE_BASELINE_MISMATCH")
            else:
                if (not isinstance(baseline, dict) or baseline.get("reset_id") != record["reset_id"]
                        or baseline.get("account_id") != record.get("account_id")
                        or baseline.get("positions") != {}
                        or baseline.get("valuation_basis") != "ACTUAL_POST_LIQUIDATION_CASH"
                        or isinstance(baseline.get("cash"), bool)
                        or not math.isfinite(float(baseline.get("cash", 0))) or float(baseline.get("cash", 0)) <= 0
                        or baseline.get("equity") != baseline.get("cash")
                        or timestamp(baseline["asof"]) < timestamp(request["requested_at"])
                        or timestamp(baseline["asof"]) > self._now()):
                    raise ValueError("RESET_STAGE_BASELINE_MISMATCH")
            if record["stage"] == "COMPLETED" and (
                    not record.get("completed_at") or timestamp(record["completed_at"]) < timestamp(baseline["asof"])
                    or record.get("completion_status") not in {"EXECUTED", "PARTIALLY_EXECUTED"}):
                raise ValueError("RESET_COMPLETION_BINDING_CHANGED")
        except (KeyError, TypeError, OverflowError) as exc:
            raise ValueError("RESET_RECORD_BINDING_CHANGED") from exc
        if record["stage"] == "COMPLETED" and self.metadata.get("signal_date") != record["signal_date"]:
            return None
        capital = self.engine._get("best_capital", {})
        connected = self.engine.mode == "moomoo_simulate" and self.engine.account_id == record.get("account_id")
        disconnected = (allow_disconnected is True and self.engine.mode == "paper"
                        and self.engine.broker is None and self.engine.account_id == self.engine.paper_account_id)
        refs = self.metadata.get("source_refs", {}).get("selected/package.json", {})
        plan_refs = self.plan.get("source_refs", {}).get("selected/package.json", {}) if self.plan else {}
        if (not self.plan or self.plan.get("reset_id") != record["reset_id"]
                or self.plan.get("policy_id") != record["policy_id"]
                or refs.get("sha256") != record["expected_package_sha256"]
                or plan_refs != refs
                or self.metadata.get("reset_id") != record["reset_id"]
                or self.metadata.get("signal_date") != record["signal_date"]
                or self.metadata.get("execution_date") != record.get("execution_date")
                or not (connected or disconnected)
                or self.engine._get("best_account", None) != record.get("account_id")
                or capital.get("account_id") != record.get("account_id")
                or capital.get("budget") != self.budget
                or capital.get("unused_cash") != record.get("unused_cash")
                or self._content_sha(self.plan) != record.get("plan_sha256")
                or self._content_sha(self.metadata) != record.get("metadata_sha256")
                or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
            raise ValueError("RESET_EXECUTION_BINDING_CHANGED")
        execution = self.engine._get("best_execution", {})
        phase = execution.get("phase")
        if phase is not None and execution.get("signal_date") != record["signal_date"]:
            raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
        if phase is not None:
            weights = {row["code"]: float(row["target_weight"]) for row in self.plan["rows"]}
            quantities = execution.get("target_quantities")
            if (execution.get("original_target_weights") != weights
                    or execution.get("original_target_cash_weight") != self.plan["target_cash_weight"]
                    or not isinstance(quantities, dict)
                    or any(not code_valid(code) or type(qty) is not int or qty < 0 for code, qty in quantities.items())
                    or not execution.get("phase_asof")):
                raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
            if phase == "SELL" and any(quantities.values()):
                raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
            manifest = execution.get("manifest")
            if manifest:
                origin = json.loads(manifest["source"])
                if origin.get("reset_id") != record["reset_id"] or origin.get("phase") != phase:
                    raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
        if record["stage"] == "ARMED" and phase not in {None, "SELL"}:
            raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
        if record["stage"] == "COMPLETED" and phase != "DONE":
            raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
        if record["stage"] == "REBUYING":
            if phase not in {None, "SELL", "BUY"}:
                raise ValueError("RESET_EXECUTION_PHASE_MISMATCH")
            if phase != "BUY" and (not self.snapshot or self.engine._pending()
                    or any(item.get("qty", 0) for item in self.snapshot.get("positions", {}).values())):
                raise ValueError("RESET_REBUY_STATE_MISSING_WITH_POSITIONS")
        if baseline is not None:
            opening = timestamp(self.metadata["next_open_utc"])
            if not opening <= timestamp(baseline["asof"]) < opening + timedelta(seconds=600):
                raise ValueError("RESET_BASELINE_OUTSIDE_EXECUTION_WINDOW")
        return record

    def _finish_reset_liquidation(self, reset, snapshot, now):
        """Record the real empty-account cash once, only after actual fills are reconciled."""
        if self.engine._pending() or any(item.get("qty", 0) for item in snapshot["positions"].values()):
            return False
        self._accept_snapshot(snapshot)  # Includes all historic + new confirmed fills and actual quantities.
        if reset.get("post_liquidation_baseline") is None:
            cash = float(snapshot["cash"]) - float(reset["unused_cash"])
            if not math.isfinite(cash) or cash <= 0:
                raise ValueError("RESET_ACTUAL_LIQUIDATION_CASH_INVALID")
            reset.update(stage="REBUYING", post_liquidation_baseline=dict(
                reset_id=reset["reset_id"], asof=now.isoformat(), cash=cash, equity=cash,
                account_id=reset["account_id"], positions={}, valuation_basis="ACTUAL_POST_LIQUIDATION_CASH"))
            self.engine._set("best_full_liquidation_reset", reset)
            self.engine._audit("FULL_LIQUIDATION_CONFIRMED", json.dumps(reset["post_liquidation_baseline"]))
        return True

    def _original_sell_stage_binding(self, record, state, *, plan=None, metadata=None, creating=False):
        """Bind the original SELL and, when present, its complete saved BUY continuation."""
        plan = self.plan if plan is None else plan
        metadata = self.metadata if metadata is None else metadata
        original = record.get("original_execution", {})
        weights = {row["code"]: row["target_weight"] for row in plan["rows"]}
        resume = original.get("resume_buy_state")
        if resume is not None and (not isinstance(resume, dict) or resume.get("phase") != "BUY"
                or resume.get("signal_date") != record.get("signal_date")
                or resume.get("original_target_weights") != weights
                or resume.get("original_target_cash_weight") != plan["target_cash_weight"]
                or not isinstance(resume.get("target_quantities"), dict)
                or any(not code_valid(code) or type(qty) is not int or qty < 0
                       for code, qty in resume.get("target_quantities", {}).items())
                or not isinstance(resume.get("processed_codes"), list)
                or any(not code_valid(code) for code in resume.get("processed_codes", []))
                or len(resume.get("processed_codes", [])) != len(set(resume.get("processed_codes", [])))
                or not resume.get("phase_asof")):
            raise ValueError("ORIGINAL_SELL_REMAINDER_SAVED_BUY_CHANGED")
        baseline_keys = {"resolved_sell_targets", "resolved_buy_targets", "new_quantity_records", "latest_execution_sha256"}
        baseline = {key: value for key, value in record.items() if key not in baseline_keys}
        baseline["account_id"] = "****" + str(record.get("account_id", ""))[-4:]
        authorized, deadline = timestamp(record["authorized_at_utc"]), timestamp(record["deadline_utc"])
        account = self.engine._get("best_account", None)
        if (record.get("original_sell_stage") is not True or record.get("quote_refresh") is not True
                or record.get("include_deferred_sells") is not True or record.get("reason") != "USER_MANUAL_ORIGINAL_SELL_STAGE"
                or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                or record.get("frozen_plan_sha256") != self._content_sha(plan)
                or record.get("frozen_refs_sha256") != self._content_sha(plan.get("source_refs", metadata.get("source_refs", {})))
                or record.get("original_execution_sha256") != self._content_sha(original)
                or record.get("original_strategy_manifest_sha256") != self._content_sha(record.get("original_strategy_manifest"))
                or original.get("phase") != "SELL"
                or original.get("signal_date") != record["signal_date"]
                or original.get("original_target_weights") != weights
                or original.get("original_target_cash_weight") != plan["target_cash_weight"]
                or not original.get("target_quantities") or not original.get("phase_asof")
                or not authorized < deadline <= authorized + timedelta(seconds=600)
                or timestamp(record["original_deadline_utc"]) > authorized
                or record.get("eligible_codes") != sorted(set(record.get("original_sell_codes", [])) | {code for code,w in weights.items() if w})
                or state.get("signal_date") != record["signal_date"] or state.get("phase") not in {"SELL", "BUY", "DONE"}
                or record.get("latest_execution_sha256") != self._content_sha(state)):
            raise ValueError("ORIGINAL_SELL_REMAINDER_BINDING_CHANGED")
        expected = {"SELL": dict(original["target_quantities"]), "BUY": dict(resume["target_quantities"]) if resume is not None else {}}
        records = record.get("new_quantity_records", [])
        if not isinstance(records, list):
            raise ValueError("ORIGINAL_SELL_REMAINDER_RESOLUTION_CHANGED")
        audit = {self._content_sha(json.loads(row[0])) for row in self.engine.db.execute(
            "SELECT detail FROM audit WHERE event=? AND time>=?", ("ORIGINAL_SELL_REMAINDER_QUANTITY_RESOLVED", record["authorized_at_utc"]))}
        for row in records:
            phase, code, qty = row.get("phase"), row.get("code"), row.get("target_qty")
            if (phase not in expected or code not in record["eligible_codes"] or type(qty) is not int or qty < 0
                    or code in expected[phase] or self._content_sha(row) not in audit
                    or row.get("source_hash") != record["source_hash"] or row.get("intent") != record["reason"]):
                raise ValueError("ORIGINAL_SELL_REMAINDER_RESOLUTION_CHANGED")
            expected[phase][code] = qty
        if expected["SELL"] != record.get("resolved_sell_targets") or expected["BUY"] != record.get("resolved_buy_targets"):
            raise ValueError("ORIGINAL_SELL_REMAINDER_QUANTITIES_CHANGED")
        if not creating:
            receipts = [json.loads(row[0]) for row in self.engine.db.execute(
                "SELECT detail FROM audit WHERE event=? AND time=?", ("BEST_ORIGINAL_SELL_REMAINDER_AUTHORIZED", record["authorized_at_utc"]))]
            if not any(self._content_sha(baseline) == self._content_sha({k:v for k,v in row.items() if k not in baseline_keys}) for row in receipts):
                raise ValueError("ORIGINAL_SELL_REMAINDER_AUTHORIZATION_CHANGED")
            latest = next((json.loads(row[0]) for row in self.engine.db.execute(
                "SELECT detail FROM audit WHERE event=? AND time>=? ORDER BY rowid DESC", ("ORIGINAL_SELL_REMAINDER_PROGRESS", record["authorized_at_utc"]))
                if json.loads(row[0]).get("authorized_at_utc") == record["authorized_at_utc"]), None)
            expected_sha = latest["execution_sha256"] if latest else record["original_execution_sha256"]
            if record["latest_execution_sha256"] != expected_sha:
                raise ValueError("ORIGINAL_SELL_REMAINDER_EXECUTION_CHANGED")
        return expected["SELL"]

    def _persist_original_sell_execution(self, record, state, now, snap, phase, new_details):
        """Retain resolved quantities and each real owner transition atomically."""
        self._original_sell_stage_binding(record, self.engine._get("best_execution", {}))
        updated = deepcopy(record)
        mapping = updated["resolved_sell_targets"] if phase == "SELL" else updated["resolved_buy_targets"]
        resolutions = []
        for code, qty in state["target_quantities"].items():
            if code not in updated["eligible_codes"] or type(qty) is not int or qty < 0:
                raise ValueError("ORIGINAL_SELL_REMAINDER_SCOPE_CHANGED")
            if code in mapping:
                if mapping[code] != qty:
                    raise ValueError("ORIGINAL_SELL_REMAINDER_RESOLVED_QUANTITY_CHANGED")
                continue
            quote = snap.get("quotes", {}).get(code)
            if not quote or code not in new_details:
                raise ValueError("ORIGINAL_SELL_REMAINDER_NEW_QUANTITY_WITHOUT_QUOTE")
            mapping[code] = qty
            resolutions.append(dict(code=code, phase=phase, target_qty=qty, **new_details[code],
                resolved_at_utc=now.isoformat(), source_hash=updated["source_hash"], intent=updated["reason"],
                quote_evidence={key:value for key,value in quote.items() if key in
                    {"asof", "price", "bid", "ask", "lot_size", "source", "currency", "tradable"}}))
        updated["new_quantity_records"].extend(resolutions)
        updated["latest_execution_sha256"] = self._content_sha(state)
        with self.engine.db:
            for key, value in (("best_execution", state), ("best_same_day_catchup", updated)):
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            for value in resolutions:
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(), "ORIGINAL_SELL_REMAINDER_QUANTITY_RESOLVED", json.dumps(value, ensure_ascii=False, allow_nan=False)))
            self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(), "ORIGINAL_SELL_REMAINDER_PROGRESS", json.dumps(
                dict(authorized_at_utc=updated["authorized_at_utc"], execution_sha256=updated["latest_execution_sha256"]), allow_nan=False)))

    def _remainder_binding(self, record, state, *, plan=None, metadata=None):
        """Bind the opt-in SELL detour to the original BUY and prior SELL evidence."""
        if record.get("original_sell_stage") is True:
            return self._original_sell_stage_binding(record, state, plan=plan, metadata=metadata)
        if record.get("quote_refresh") is True:
            return self._manual_quote_refresh_binding(record, state, plan=plan, metadata=metadata)
        plan = self.plan if plan is None else plan
        metadata = self.metadata if metadata is None else metadata
        if not isinstance(plan, dict) or not isinstance(metadata, dict):
            raise ValueError("REMAINDER_FROZEN_PLAN_REQUIRED")
        account = self.engine._get("best_account", None)
        if (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != account or str(self.engine.broker.account_id) != account):
            raise ValueError("REMAINDER_ORIGINAL_SIMULATE_CONNECTION_REQUIRED")
        frozen = record.get("original_buy", {})
        targets = record.get("deferred_sell_targets", {})
        evidence = record.get("deferred_sell_manifest", {})
        authorized, deadline = timestamp(record["authorized_at_utc"]), timestamp(record["deadline_utc"])
        weights = {row["code"]: float(row["target_weight"]) for row in plan["rows"]}
        refs = plan.get("source_refs", metadata.get("source_refs", {}))
        if (record.get("include_deferred_sells") is not True
                or record.get("reason") != "USER_REQUESTED_SAME_DAY_SIMULATE_REMAINDER"
                or record.get("frozen_plan_sha256") != self._content_sha(plan)
                or record.get("frozen_refs_sha256") != self._content_sha(refs)
                or not authorized < deadline <= authorized + timedelta(seconds=600)
                or timestamp(record["original_deadline_utc"]) > authorized
                or not isinstance(frozen, dict) or not isinstance(targets, dict)
                or not isinstance(frozen.get("target_quantities"), dict) or not frozen["target_quantities"]
                or not isinstance(frozen.get("phase_asof"), str)
                or not isinstance(evidence, dict)
                or record.get("deferred_sell_manifest_sha256") != self._content_sha(evidence)):
            raise ValueError("REMAINDER_AUTHORIZATION_BINDING_INVALID")
        if any(not code_valid(code) or type(qty) is not int or qty < 0 for code, qty in targets.items()):
            raise ValueError("REMAINDER_SELL_TARGET_INVALID")
        original_codes = frozen.get("deferred_codes", [])
        if len(original_codes) != len(set(original_codes)) or set(original_codes) != set(targets):
            raise ValueError("REMAINDER_DEFERRED_CODES_CHANGED")
        if targets:
            try:
                origin = json.loads(evidence["source"])
                rows = evidence["targets"]
                evidenced = {row["code"]: row["target_qty"] for row in rows}
                valid_evidence = (evidence.get("strategy_id") == self.strategy_id and len(evidenced) == len(rows)
                    and origin.get("kind") == "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                    and origin.get("phase") == "SELL" and origin.get("signal_date") == record["signal_date"]
                    and origin.get("source_hash") == record["source_hash"]
                    and timestamp(origin["next_open_utc"]) == timestamp(metadata["next_open_utc"])
                    and timestamp(metadata["next_open_utc"]) <= timestamp(evidence["asof"]) < timestamp(evidence["expires_at"])
                    and timestamp(evidence["expires_at"]) == timestamp(record["original_deadline_utc"]))
            except (KeyError, TypeError, ValueError):
                valid_evidence, evidenced = False, {}
            for code, qty in targets.items():
                if code not in weights or (weights[code] == 0 and qty != 0):
                    raise ValueError("REMAINDER_SELL_TARGET_NOT_IN_PLAN")
                if weights[code] != 0 and (not valid_evidence or evidenced.get(code) != qty):
                    raise ValueError("REMAINDER_ORIGINAL_SELL_EVIDENCE_REQUIRED")
        phase = state.get("phase")
        if phase == "BUY":
            buy = state
            deferred = [row["code"] for row in buy.get("deferred_sells", [])]
            if len(deferred) != len(set(deferred)) or not set(deferred).issubset(targets):
                raise ValueError("REMAINDER_DEFERRED_CODES_CHANGED")
        elif phase == "SELL":
            buy = state.get("resume_buy_state", {})
            codes = state.get("sell_codes", [])
            if (not codes or len(codes) != len(set(codes)) or not set(codes).issubset(targets)
                    or any(code not in targets or qty != targets[code]
                           for code, qty in state.get("target_quantities", {}).items())):
                raise ValueError("REMAINDER_SELL_TRANSITION_CHANGED")
        else:
            raise ValueError("REMAINDER_REQUIRES_ORIGINAL_BUY_OR_BOUND_SELL")
        current = buy.get("target_quantities", {})
        if any(code in frozen["target_quantities"] and frozen["target_quantities"][code] != qty
               for code, qty in targets.items()):
            raise ValueError("REMAINDER_ORIGINAL_BUY_SELL_TARGET_CONFLICT")
        if isinstance(current, dict) and any(code in current and current[code] != qty
                                             for code, qty in targets.items()):
            raise ValueError("REMAINDER_RESUMED_SELL_TARGET_CHANGED")
        if (buy.get("phase") != "BUY" or buy.get("signal_date") != record["signal_date"]
                or buy.get("phase_asof") != frozen["phase_asof"]
                or not isinstance(current, dict)
                or any(current.get(code) != qty for code, qty in frozen["target_quantities"].items())
                or not set(frozen.get("processed_codes", [])).issubset(buy.get("processed_codes", []))
                or buy.get("original_target_weights") != weights
                or buy.get("original_target_cash_weight") != plan["target_cash_weight"]):
            raise ValueError("REMAINDER_ORIGINAL_BUY_CHANGED")
        return targets

    def _manual_quote_refresh_binding(self, record, state, *, plan=None, metadata=None, creating=False):
        """Validate a new, explicit residual intent without inventing historical SELL quantities."""
        plan = self.plan if plan is None else plan
        metadata = self.metadata if metadata is None else metadata
        if not isinstance(plan, dict) or not isinstance(record, dict) or not isinstance(state, dict):
            raise ValueError("MANUAL_REMAINDER_AUTHORIZATION_CHANGED")
        if not creating:
            mutable = {"deferred_sell_targets", "deferred_buy_targets", "resolved_buy_targets", "new_quantity_records"}
            baseline = {key: value for key, value in record.items() if key not in mutable}
            baseline["account_id"] = "****" + str(record.get("account_id", ""))[-4:]
            evidence = [json.loads(row[0]) for row in self.engine.db.execute(
                "SELECT detail FROM audit WHERE event=? AND time=?", ("BEST_MANUAL_REMAINDER_QUOTE_REFRESH_AUTHORIZED", record["authorized_at_utc"]))]
            if not any(self._content_sha(baseline) == self._content_sha({key: value for key, value in row.items() if key not in mutable}) for row in evidence):
                raise ValueError("MANUAL_REMAINDER_AUTHORIZATION_AUDIT_CHANGED")
        original = record.get("original_execution", {})
        deferred = [row["code"] for row in original.get("deferred_sells", [])]
        weights = {row["code"]: row["target_weight"] for row in plan["rows"]}
        eligible = ({code for code, weight in weights.items() if weight}
                    - set(original.get("processed_codes", []))) | set(deferred)
        authorized, deadline = timestamp(record["authorized_at_utc"]), timestamp(record["deadline_utc"])
        if (record.get("quote_refresh") is not True or record.get("include_deferred_sells") is not True
                or record.get("reason") != "USER_MANUAL_REMAINDER_QUOTE_REFRESH"
                or record.get("frozen_plan_sha256") != self._content_sha(plan)
                or record.get("frozen_refs_sha256") != self._content_sha(plan.get("source_refs", metadata.get("source_refs", {})))
                or record.get("original_execution_sha256") != self._content_sha(original)
                or record.get("original_strategy_manifest_sha256") != self._content_sha(record.get("original_strategy_manifest"))
                or original.get("phase") != "BUY" or original.get("signal_date") != record["signal_date"]
                or not original.get("target_quantities") or not original.get("phase_asof")
                or record.get("eligible_codes") != sorted(eligible)
                or len(deferred) != len(set(deferred))
                or not authorized < deadline <= authorized + timedelta(seconds=600)
                or timestamp(record["original_deadline_utc"]) > authorized
                or state.get("signal_date") != record["signal_date"] or state.get("phase") not in {"BUY", "SELL"}):
            raise ValueError("MANUAL_REMAINDER_AUTHORIZATION_CHANGED")
        resolved = record.get("deferred_sell_targets", {})
        deferred_buys = record.get("deferred_buy_targets", {})
        new_buys = record.get("resolved_buy_targets", {})
        if (not isinstance(resolved, dict) or not isinstance(new_buys, dict) or not isinstance(deferred_buys, dict)
                or set(deferred_buys) != set(resolved) or set(deferred) & set(original["target_quantities"])
                or not set(resolved).issubset(deferred) or not set(new_buys).issubset(eligible - set(deferred))
                or any(not code_valid(code) or type(qty) is not int or qty < 0
                       for mapping in (resolved, deferred_buys, new_buys, original["target_quantities"]) for code, qty in mapping.items())):
            raise ValueError("MANUAL_REMAINDER_QUANTITY_BINDING_CHANGED")
        buy = state if state["phase"] == "BUY" else state.get("resume_buy_state", {})
        if (buy.get("phase_asof") != original.get("phase_asof")
                or not set(original.get("processed_codes", [])).issubset(buy.get("processed_codes", []))
                or any(buy.get("target_quantities", {}).get(code) != qty
                       for code, qty in original["target_quantities"].items())):
            raise ValueError("MANUAL_REMAINDER_ORIGINAL_BUY_CHANGED")
        for mapping in (deferred_buys, new_buys):
            for code, qty in mapping.items():
                observed = buy.get("target_quantities", {}).get(code)
                if observed is not None and observed != qty:
                    raise ValueError("MANUAL_REMAINDER_RESOLVED_BUY_CHANGED")
        if state["phase"] == "SELL":
            if any(state.get("target_quantities", {}).get(code, qty) != qty for code, qty in resolved.items()):
                raise ValueError("MANUAL_REMAINDER_RESOLVED_SELL_CHANGED")
        records = record.get("new_quantity_records", [])
        if not isinstance(records, list):
            raise ValueError("MANUAL_REMAINDER_RESOLUTION_EVIDENCE_CHANGED")
        audit = {self._content_sha(json.loads(row[0])) for row in self.engine.db.execute(
            "SELECT detail FROM audit WHERE event=? AND time>=?", ("MANUAL_REMAINDER_QUOTE_TARGET_RESOLVED", record["authorized_at_utc"]))}
        expected = {(code, "SELL") for code in resolved} | {(code, "BUY") for code in new_buys}
        if {(row.get("code"), row.get("phase")) for row in records} != expected or len(records) != len(expected):
            raise ValueError("MANUAL_REMAINDER_RESOLUTION_EVIDENCE_CHANGED")
        for row in records:
            code = row["code"]
            if self._content_sha(row) not in audit or row.get("source_hash") != record["source_hash"] or row.get("intent") != record["reason"]:
                raise ValueError("MANUAL_REMAINDER_RESOLUTION_EVIDENCE_CHANGED")
            if row["phase"] == "SELL":
                if (row.get("target_qty") != resolved[code] or row.get("new_sell_target") != resolved[code] or row.get("new_buy_target") != deferred_buys[code]
                        or row.get("desired") != deferred_buys[code] or min(row["desired"], row["held_before"]) != resolved[code]):
                    raise ValueError("MANUAL_REMAINDER_RESOLUTION_EVIDENCE_CHANGED")
            elif row.get("target_qty") != new_buys[code]:
                raise ValueError("MANUAL_REMAINDER_RESOLUTION_EVIDENCE_CHANGED")
        if state["phase"] == "SELL" and not set(state.get("sell_codes", [])).issubset(deferred):
            raise ValueError("MANUAL_REMAINDER_SELL_SCOPE_CHANGED")

    def _persist_manual_execution(self, record, state, now, snap, phase, new_details):
        """Atomically retain each newly resolved target and its new-asof quote evidence."""
        updated = deepcopy(record)
        mapping = updated["deferred_sell_targets"] if phase == "SELL" else updated["resolved_buy_targets"]
        original = updated["original_execution"]
        eligible = set(updated["eligible_codes"])
        if phase == "SELL":
            eligible.intersection_update(row["code"] for row in original["deferred_sells"])
        else:
            eligible.difference_update(original["target_quantities"])
            eligible.difference_update(row["code"] for row in original["deferred_sells"])
        renewal = self._catchup_renewal(record, self.engine._get("best_execution", {}))
        if renewal is not None:
            eligible.intersection_update(renewal["allowed_codes"])
        resolutions = []
        for code in sorted(eligible & set(state["target_quantities"])):
            qty = state["target_quantities"][code]
            if code in mapping:
                if mapping[code] != qty:
                    raise ValueError("MANUAL_REMAINDER_RESOLVED_QUANTITY_CHANGED")
                continue
            quote = snap.get("quotes", {}).get(code)
            if not quote:
                raise ValueError("MANUAL_REMAINDER_NEW_QUANTITY_WITHOUT_QUOTE")
            mapping[code] = qty
            detail = new_details[code]
            if phase == "SELL":
                updated["deferred_buy_targets"][code] = detail["desired"]
            resolutions.append(dict(code=code, phase=phase, target_qty=qty, **detail, resolved_at_utc=now.isoformat(),
                source_hash=updated["source_hash"], intent=updated["reason"],
                quote_evidence={key: value for key, value in quote.items() if key in
                    {"asof", "quote_time", "timestamp", "observed_at", "price", "bid", "ask", "lot_size", "source", "currency"}}))
        updated.setdefault("new_quantity_records", []).extend(resolutions)
        with self.engine.db:
            for key, value in (("best_execution", state), ("best_same_day_catchup", updated)):
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                    (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
            for value in resolutions:
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(),
                    "MANUAL_REMAINDER_QUOTE_TARGET_RESOLVED", json.dumps(value, ensure_ascii=False, allow_nan=False)))

    def _catchup_renewal(self, prior, state, *, plan=None, metadata=None, renewal=None, creating=False):
        """Validate one explicit lease; the original intent and quantity audit stay intact."""
        plan = self.plan if plan is None else plan
        metadata = self.metadata if metadata is None else metadata
        renewal = self.engine._get("best_same_day_catchup_renewal", None) if renewal is None else renewal
        if not isinstance(renewal, dict) or renewal.get("signal_date") != metadata.get("signal_date"):
            return None
        required = {"schema_version", "renewal_id", "signal_date", "execution_date", "account_id", "budget",
            "authorized_at_utc", "deadline_utc", "expected_prior_sha256", "prior_permission_raw",
            "prior_permission_bytes_sha256", "plan_sha256", "refs_sha256", "allowed_codes", "remaining_codes",
            "execution_snapshot", "execution_sha256", "reason"}
        if set(renewal) != required or renewal.get("schema_version") != 1:
            raise ValueError("CATCHUP_RENEWAL_SCHEMA_CHANGED")
        try:
            raw = renewal["prior_permission_raw"]
            archived = json.loads(raw)
            authorized, deadline = timestamp(renewal["authorized_at_utc"]), timestamp(renewal["deadline_utc"])
            close, opening = timestamp(metadata["next_close_utc"]), timestamp(metadata["next_open_utc"])
            allowed = renewal["allowed_codes"]
            account = self.engine._get("best_account", None)
            capital = self.engine._get("best_capital", {})
            mutable = {"deferred_sell_targets", "deferred_buy_targets", "resolved_buy_targets", "new_quantity_records"}
            baseline = lambda value: {key: item for key, item in value.items() if key not in mutable}
            if (renewal["reason"] != "USER_EXPLICIT_ONCE_SAME_DAY_SIMULATE_RENEWAL"
                    or type(raw) is not str or hashlib.sha256(raw.encode("utf-8")).hexdigest() != renewal["prior_permission_bytes_sha256"]
                    or self._content_sha(archived) != renewal["expected_prior_sha256"]
                    or archived.get("reason") != "USER_MANUAL_REMAINDER_QUOTE_REFRESH"
                    or archived.get("quote_refresh") is not True or archived.get("original_sell_stage") is True
                    or baseline(prior) != baseline(archived)
                    or renewal["plan_sha256"] != self._content_sha(plan)
                    or renewal["refs_sha256"] != self._content_sha(plan.get("source_refs", metadata.get("source_refs", {})))
                    or renewal["account_id"] != account or self.engine.account_id != account
                    or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                    or str(self.engine.broker.account_id) != account
                    or capital.get("account_id") != account or capital.get("budget") != self.budget
                    or renewal["budget"] != self.budget or archived.get("budget") != self.budget
                    or archived.get("account_id") != account or self.engine.halt_event.is_set()
                    or renewal["execution_date"] != metadata["execution_date"]
                    or archived.get("execution_date") != metadata["execution_date"]
                    or archived.get("signal_date") != metadata["signal_date"]
                    or not timestamp(archived["deadline_utc"]) <= authorized < deadline <= min(authorized + timedelta(seconds=600), close)
                    or opening.astimezone(ZoneInfo("America/New_York")).date().isoformat() != renewal["execution_date"]
                    or authorized.astimezone(ZoneInfo("America/New_York")).date().isoformat() != renewal["execution_date"]
                    or deadline.astimezone(ZoneInfo("America/New_York")).date().isoformat() != renewal["execution_date"]
                    or not isinstance(allowed, list) or not allowed or allowed != sorted(set(allowed))
                    or any(not code_valid(code) for code in allowed)
                    or not set(allowed).issubset(renewal["remaining_codes"])
                    or self._content_sha(renewal["execution_snapshot"]) != renewal["execution_sha256"]):
                raise ValueError("CATCHUP_RENEWAL_BINDING_CHANGED")
            original = renewal["execution_snapshot"]
            original_buy = original if original.get("phase") == "BUY" else original.get("resume_buy_state", {})
            remaining = set(archived["eligible_codes"]) - set(original_buy.get("processed_codes", []))
            if renewal["remaining_codes"] != sorted(remaining) or original_buy.get("phase") != "BUY":
                raise ValueError("CATCHUP_RENEWAL_REMAINING_CHANGED")
            for name in mutable - {"new_quantity_records"}:
                old, current = archived[name], prior[name]
                if (any(current.get(code) != qty for code, qty in old.items())
                        or not (set(current) - set(old)).issubset(allowed)):
                    raise ValueError("CATCHUP_RENEWAL_RESOLVED_QUANTITY_CHANGED")
            old_records, current_records = archived["new_quantity_records"], prior["new_quantity_records"]
            if (current_records[:len(old_records)] != old_records
                    or any(row.get("code") not in allowed for row in current_records[len(old_records):])):
                raise ValueError("CATCHUP_RENEWAL_QUANTITY_RECORD_PREFIX_CHANGED")
            buy = state if state.get("phase") in {"BUY", "DONE"} else state.get("resume_buy_state", {})
            if (state.get("phase") not in {"BUY", "SELL", "DONE"}
                    or buy.get("phase_asof") != original_buy.get("phase_asof")
                    or not set(original_buy.get("processed_codes", [])).issubset(buy.get("processed_codes", []))
                    or any(buy.get("target_quantities", {}).get(code) != qty
                           for code, qty in original_buy.get("target_quantities", {}).items())
                    or not (set(buy.get("target_quantities", {})) - set(original_buy.get("target_quantities", {}))).issubset(allowed)):
                raise ValueError("CATCHUP_RENEWAL_EXECUTION_QUANTITY_CHANGED")
            if not creating:
                rows = self.engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
                    ("BEST_CATCHUP_RENEWAL_AUTHORIZED", renewal["authorized_at_utc"]))
                if not any(self._content_sha(json.loads(row[0])) == self._content_sha(renewal) for row in rows):
                    raise ValueError("CATCHUP_RENEWAL_AUTHORIZATION_AUDIT_CHANGED")
                rows = self.engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
                    ("BEST_CATCHUP_RENEWAL_PRIOR_ARCHIVED", renewal["authorized_at_utc"]))
                if not any(row[0] == raw for row in rows):
                    raise ValueError("CATCHUP_RENEWAL_PRIOR_ARCHIVE_CHANGED")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("CATCHUP_RENEWAL_BINDING_CHANGED") from exc
        return renewal

    def renew_catchup(self, *, execution_date, deadline_utc, expected_prior_sha256, renewal_id, now, account_id, allowed_codes):
        """Record one newly authorized same-day residual lease, without replacing its old intent."""
        self._require_legacy_strategy()
        with self.lock:
            if not self.stop_event.is_set() or (self.worker and self.worker.is_alive()):
                raise ValueError("CATCHUP_RENEWAL_REQUIRES_STOPPED_WORKER")
            self.engine._require_stopped()
            if self.engine._pending() or self.engine.halt_event.is_set():
                raise ValueError("CATCHUP_RENEWAL_REQUIRES_RECONCILED_ACCOUNT")
            if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
                raise ValueError("CATCHUP_RENEWAL_AWARE_CLOCK_REQUIRED")
            now, deadline = now.astimezone(timezone.utc), timestamp(deadline_utc)
            if (not isinstance(renewal_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", renewal_id)
                    or not isinstance(expected_prior_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_prior_sha256)
                    or not isinstance(allowed_codes, list) or not allowed_codes or any(not isinstance(code,str) or not code_valid(code) for code in allowed_codes)
                    or len(set(allowed_codes)) != len(allowed_codes)):
                raise ValueError("CATCHUP_RENEWAL_EXPLICIT_BINDING_REQUIRED")
            allowed_codes = sorted(allowed_codes)
            saved = self.engine._get("best_plan", {})
            plan, metadata = saved.get("plan"), saved.get("metadata")
            row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_same_day_catchup'").fetchone()
            if not row or not isinstance(plan, dict) or not isinstance(metadata, dict):
                raise ValueError("CATCHUP_RENEWAL_ORIGINAL_INTENT_REQUIRED")
            raw, prior, state = row[0], json.loads(row[0]), self.engine._get("best_execution", {})
            if (account_id != self.engine._get("best_account", None)
                    or metadata.get("execution_date") != execution_date
                    or now.astimezone(ZoneInfo("America/New_York")).date().isoformat() != execution_date
                    or not self.allow_partial_quotes):
                raise ValueError("CATCHUP_RENEWAL_SAME_ACCOUNT_SESSION_REQUIRED")
            existing = self.engine._get("best_same_day_catchup_renewal", None)
            if isinstance(existing, dict) and existing.get("signal_date") == metadata.get("signal_date"):
                if any(existing.get(key) != value for key,value in {
                        "renewal_id":renewal_id,"execution_date":execution_date,"deadline_utc":deadline.isoformat(),
                        "expected_prior_sha256":expected_prior_sha256,"allowed_codes":allowed_codes,"account_id":account_id}.items()):
                    raise ValueError("CATCHUP_RENEWAL_ALREADY_AUTHORIZED")
                self._catchup_renewal(prior, state, plan=plan, metadata=metadata, renewal=existing)
                return existing
            if (self._content_sha(prior) != expected_prior_sha256 or prior.get("quote_refresh") is not True
                    or prior.get("original_sell_stage") is True or state.get("phase") not in {"BUY","SELL"}
                    or state.get("signal_date") != metadata.get("signal_date")
                    or not timestamp(prior["deadline_utc"]) <= now < deadline <= min(now+timedelta(seconds=600), timestamp(metadata["next_close_utc"]))):
                raise ValueError("CATCHUP_RENEWAL_EXPIRED_ORIGINAL_BINDING_REQUIRED")
            self._manual_quote_refresh_binding(prior, state, plan=plan, metadata=metadata)
            buy = state if state["phase"] == "BUY" else state["resume_buy_state"]
            remaining = sorted(set(prior["eligible_codes"]) - set(buy.get("processed_codes", [])))
            if not set(allowed_codes).issubset(remaining):
                raise ValueError("CATCHUP_RENEWAL_ONLY_UNPROCESSED_CODES")
            renewal = dict(schema_version=1,renewal_id=renewal_id,signal_date=metadata["signal_date"],
                execution_date=execution_date,account_id=account_id,budget=self.budget,authorized_at_utc=now.isoformat(),
                deadline_utc=deadline.isoformat(),expected_prior_sha256=expected_prior_sha256,prior_permission_raw=raw,
                prior_permission_bytes_sha256=hashlib.sha256(raw.encode("utf-8")).hexdigest(),plan_sha256=self._content_sha(plan),
                refs_sha256=self._content_sha(plan.get("source_refs",metadata.get("source_refs",{}))),allowed_codes=allowed_codes,
                remaining_codes=remaining,execution_snapshot=deepcopy(state),execution_sha256=self._content_sha(state),
                reason="USER_EXPLICIT_ONCE_SAME_DAY_SIMULATE_RENEWAL")
            self._catchup_renewal(prior,state,plan=plan,metadata=metadata,renewal=renewal,creating=True)
            with self.engine.db:
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(now.isoformat(),"BEST_CATCHUP_RENEWAL_PRIOR_ARCHIVED",raw))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(now.isoformat(),"BEST_CATCHUP_RENEWAL_AUTHORIZED",json.dumps(renewal,ensure_ascii=False,allow_nan=False)))
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("best_same_day_catchup_renewal",json.dumps(renewal,ensure_ascii=False,allow_nan=False)))
            return renewal

    def _catchup_end(self):
        """Return a single explicitly authorized same-session deadline, if any."""
        if self.strategy_id != SID or self.engine._get("best_strategy_binding", None) is not None:
            return None
        record = self._scoped_legacy_setting("best_same_day_catchup", None)
        if not isinstance(record, dict) or record.get("signal_date") != self.metadata.get("signal_date"):
            return None
        state = self.engine._get("best_execution", {})
        if record.get("include_deferred_sells") is True:
            if state.get("phase") == "DONE":
                return None
            self._remainder_binding(record, state)
        elif state.get("phase") != "BUY" or state.get("deferred_sells"):
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
        renewal = self._catchup_renewal(record, state)
        return timestamp(renewal["deadline_utc"]) if renewal is not None else deadline

    def authorize_catchup(self, *, execution_date, deadline_utc, account_id, now, include_deferred_sells=False, quote_refresh=False):
        """Persist this user's one-day SIMULATE buy instruction while execution is stopped."""
        self._require_legacy_strategy()
        if type(quote_refresh) is not bool or (quote_refresh and not include_deferred_sells):
            raise ValueError("quote_refresh requires an explicit boolean and the same-day remainder mode")
        if type(include_deferred_sells) is not bool:
            raise ValueError("include_deferred_sells 必须是明确布尔值")
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
            prior = self._scoped_legacy_setting("best_same_day_catchup", None)
            original_sell_stage = bool(include_deferred_sells and quote_refresh and
                (state.get("phase") == "SELL"
                 or (isinstance(prior, dict) and prior.get("signal_date") == metadata["signal_date"]
                     and prior.get("original_sell_stage") is True)))
            if include_deferred_sells:
                if (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                        or self.engine.account_id != account or str(self.engine.broker.account_id) != account):
                    raise ValueError("REMAINDER_ORIGINAL_SIMULATE_CONNECTION_REQUIRED")
                accounts = self.engine.connection.get("accounts", [])
                if accounts:
                    selected = [item for item in accounts if str(item.get("account_id")) == account]
                    if len(selected) != 1 or selected[0].get("market") != "US" or selected[0].get("environment") != "SIMULATE":
                        raise ValueError("REMAINDER_ORIGINAL_SIMULATE_CONNECTION_REQUIRED")
            original = state.get("manifest") or {}
            if not original:
                row = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (self.strategy_id,)).fetchone()
                original = json.loads(row[0]) if row else {}
            ny = ZoneInfo("America/New_York")
            opening = timestamp(metadata["next_open_utc"])
            close = timestamp(metadata["next_close_utc"])
            scheduled = self._scheduled_open(metadata["next_open_utc"])
            if (metadata.get("execution_date") != execution_date
                    or metadata.get("signal_date") != state.get("signal_date")
                    or state.get("phase") not in {"SELL", "BUY"}
                    or (state.get("phase") != "BUY" and not original_sell_stage) or original.get("strategy_id") != self.strategy_id
                    or (state.get("deferred_sells") and not include_deferred_sells) or not state.get("target_quantities")
                    or not self.allow_partial_quotes
                    or opening.astimezone(ny).date().isoformat() != execution_date
                    or now.astimezone(ny).date().isoformat() != execution_date
                    or not scheduled < now < deadline <= close
                    or deadline.astimezone(ny).date().isoformat() != execution_date
                    or (include_deferred_sells and deadline > now + timedelta(seconds=600))):
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
            prior = self._scoped_legacy_setting("best_same_day_catchup", None)
            if isinstance(prior, dict) and prior.get("signal_date") == metadata["signal_date"]:
                if (prior.get("deadline_utc") == deadline.isoformat()
                        and prior.get("account_id") == account and prior.get("source_hash") == source_hash
                        and prior.get("include_deferred_sells", False) is include_deferred_sells
                        and prior.get("quote_refresh", False) is quote_refresh):
                    if include_deferred_sells:
                        self._remainder_binding(prior, state, plan=plan, metadata=metadata)
                    return prior
                raise ValueError("本信号已有不同的当日补单授权，禁止覆盖")
            if timestamp(original["expires_at"]) > now:
                raise ValueError("原委托窗口尚未结束，无需补单")
            rows = [dict(row) for row in self.engine.db.execute(
                "SELECT * FROM orders WHERE strategy_id=? AND mode='moomoo_simulate' AND account_id=?",
                (self.strategy_id, account)) if timestamp(row["created_at"]) >= opening]
            def original_terminal(row):
                if row["status"] in {"FILLED_ALL", "CANCELLED_ALL", "CANCELLED_PART", "FAILED"}:
                    return True
                if not include_deferred_sells or row["status"] != "CANCELLED_BEFORE_SEND" or row["order_id"]:
                    return False
                fill = self.engine.db.execute("SELECT payload FROM order_fills WHERE id=?", (row["id"],)).fetchone()
                if fill is None:
                    return True
                value = json.loads(fill[0])
                return (all(value.get(key) in (None, 0) and not isinstance(value.get(key), bool)
                            for key in ("fill_qty", "dealt_qty"))
                        and all(value.get(key) is None for key in ("fill_price", "dealt_avg_price", "filled_at")))
            if not rows or not all(original_terminal(row) for row in rows):
                raise ValueError("今天的原券商委托尚未全部终结并核对")
            record = dict(signal_date=metadata["signal_date"], execution_date=execution_date,
                account_id=account, budget=self.budget, source_hash=source_hash,
                authorized_at_utc=now.isoformat(), deadline_utc=deadline.isoformat(),
                original_deadline_utc=timestamp(original["expires_at"]).isoformat(),
                original_order_count=len(rows), reason="USER_REQUESTED_SAME_DAY_SIMULATE_BUY_CATCHUP")
            if include_deferred_sells:
                row = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (self.strategy_id,)).fetchone()
                evidence = json.loads(row[0]) if row else {}
                if original_sell_stage:
                    if (state.get("phase") != "SELL" or origin.get("phase") != "SELL" or self._active_full_reset()):
                        raise ValueError("ORIGINAL_SELL_REMAINDER_MAIN_STAGE_REQUIRED")
                    sell_codes = sorted(set(state["target_quantities"]) | set(self.snapshot.get("positions", {})))
                    record.update(include_deferred_sells=True, quote_refresh=True, original_sell_stage=True,
                        reason="USER_MANUAL_ORIGINAL_SELL_STAGE", frozen_plan_sha256=self._content_sha(plan),
                        frozen_refs_sha256=self._content_sha(plan.get("source_refs", metadata.get("source_refs", {}))),
                        original_execution=deepcopy(state), original_execution_sha256=self._content_sha(state),
                        original_strategy_manifest=deepcopy(evidence), original_strategy_manifest_sha256=self._content_sha(evidence),
                        original_sell_codes=sell_codes, eligible_codes=sorted(set(sell_codes) | {row["code"] for row in plan["rows"] if row["target_weight"]}),
                        resolved_sell_targets=dict(state["target_quantities"]),
                        resolved_buy_targets=dict(state["resume_buy_state"]["target_quantities"]) if state.get("resume_buy_state") is not None else {},
                        new_quantity_records=[],
                        latest_execution_sha256=self._content_sha(state))
                    self._original_sell_stage_binding(record, state, plan=plan, metadata=metadata, creating=True)
                    with self.engine.db:
                        self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_same_day_catchup", json.dumps(record, ensure_ascii=False, allow_nan=False)))
                        self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(), "BEST_ORIGINAL_SELL_REMAINDER_AUTHORIZED", json.dumps({**record, "account_id":"****"+account[-4:]}, ensure_ascii=False, allow_nan=False)))
                    return record
                if quote_refresh:
                    original = deepcopy(state)
                    weights = {row["code"]: row["target_weight"] for row in plan["rows"]}
                    eligible = ({code for code, weight in weights.items() if weight}
                                - set(state.get("processed_codes", []))) | {row["code"] for row in state.get("deferred_sells", [])}
                    if not eligible:
                        raise ValueError("MANUAL_REMAINDER_NO_UNPROCESSED_TARGETS")
                    record.update(include_deferred_sells=True, quote_refresh=True,
                        reason="USER_MANUAL_REMAINDER_QUOTE_REFRESH", frozen_plan_sha256=self._content_sha(plan),
                        frozen_refs_sha256=self._content_sha(plan.get("source_refs", metadata.get("source_refs", {}))),
                        original_execution=original, original_execution_sha256=self._content_sha(original),
                        original_strategy_manifest=deepcopy(evidence), original_strategy_manifest_sha256=self._content_sha(evidence),
                        eligible_codes=sorted(eligible), deferred_sell_targets={}, deferred_buy_targets={}, resolved_buy_targets={}, new_quantity_records=[])
                    self._manual_quote_refresh_binding(record, state, plan=plan, metadata=metadata, creating=True)
                    with self.engine.db:
                        self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_same_day_catchup",
                            json.dumps(record, ensure_ascii=False, allow_nan=False)))
                        self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(),
                            "BEST_MANUAL_REMAINDER_QUOTE_REFRESH_AUTHORIZED", json.dumps({
                                **record, "account_id": "****" + account[-4:]}, ensure_ascii=False, allow_nan=False)))
                    return record
                deferred = [item["code"] for item in state.get("deferred_sells", [])]
                if len(deferred) != len(set(deferred)):
                    raise ValueError("REMAINDER_DEFERRED_CODES_CHANGED")
                weights = {item["code"]: float(item["target_weight"]) for item in plan["rows"]}
                evidence_targets = {item["code"]: item["target_qty"] for item in evidence.get("targets", [])}
                sell_targets = {}
                for code in deferred:
                    if code not in weights or (weights[code] != 0 and code not in evidence_targets):
                        raise ValueError("REMAINDER_ORIGINAL_SELL_EVIDENCE_REQUIRED")
                    sell_targets[code] = 0 if weights[code] == 0 else evidence_targets[code]
                record.update(include_deferred_sells=True, reason="USER_REQUESTED_SAME_DAY_SIMULATE_REMAINDER",
                    frozen_plan_sha256=self._content_sha(plan),
                    frozen_refs_sha256=self._content_sha(plan.get("source_refs", metadata.get("source_refs", {}))),
                    original_buy=json.loads(json.dumps({"phase_asof":state.get("phase_asof"),
                        "target_quantities":state["target_quantities"], "processed_codes":state.get("processed_codes", []),
                        "deferred_codes":deferred})), deferred_sell_targets=sell_targets,
                    deferred_sell_manifest=evidence, deferred_sell_manifest_sha256=self._content_sha(evidence))
                self._remainder_binding(record, state, plan=plan, metadata=metadata)
            self.engine._set("best_same_day_catchup", record)
            self.engine._audit("BEST_SAME_DAY_CATCHUP_AUTHORIZED", json.dumps({
                **record, "account_id": "****" + account[-4:]}, ensure_ascii=False))
            return record

    def _native_first_binding(self, *, clock=None, source=False):
        """Native-reset custody only; never creates a phase, target or timing grant."""
        epoch = self._native_reset_record()
        bootstrap = self._native_reset_bootstrap_record(epoch)
        saved = self.engine._get("best_plan", {})
        plan, metadata = saved.get("plan", {}), saved.get("metadata", {})
        account = epoch["new_account_id"]
        if (self.strategy_id != "R10_DIRECT_H5_RIDGE_MID" or epoch["target_strategy_id"] != self.strategy_id
                or not bootstrap or bootstrap["plan_sha256"] != self._content_sha(plan)
                or self.plan != plan or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                or self.engine._get("best_account",None) != account or self.budget != 10000
                or plan.get("strategy_id") != self.strategy_id or plan.get("status") != "READY"
                or type(plan.get("model_fit_calls")) is not int or plan["model_fit_calls"] != 0
                or metadata.get("account_state_origin") != bootstrap["origin"]
                or metadata.get("data_gaps") or metadata.get("status") not in {"READY","OPEN_WINDOW","MISSED_OPEN"}
                or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600 or not self.allow_partial_quotes):
            raise ValueError("NATIVE_FIRST_EXECUTION_BOOTSTRAP_OR_PLAN_CHANGED")
        archive = metadata.get("archive")
        from .applied_source import _reference
        if not isinstance(archive,dict) or set(archive) != {"path","sha256"}:
            raise ValueError("NATIVE_FIRST_EXECUTION_SOURCE_ARCHIVE_REQUIRED")
        _reference(archive["path"],archive["sha256"])
        current = None
        if source:
            from .cohort import Cohort
            self._pending_repair_guard()
            current = Cohort._book_source_data(self.strategy_id,self.source.status(now=clock))
            if (current.get("status") not in {"READY","OPEN_WINDOW","MISSED_OPEN"} or current.get("data_gaps")
                    or any(current.get(k) != metadata.get(k) for k in
                        ("signal_date","execution_date","next_open_utc","signal_close_utc","next_close_utc"))):
                raise ValueError("NATIVE_FIRST_EXECUTION_CURRENT_SOURCE_CHANGED")
            Cohort._match_source_refs(plan.get("source_refs"),current,"NATIVE_FIRST_EXECUTION_CURRENT_SOURCE_CHANGED")
        return epoch,bootstrap,saved,current

    def _native_first_record(self, clock=None, *, source=False):
        row = self.engine.db.execute("SELECT value FROM settings WHERE key='best_native_first_execution' "
            "AND typeof(value)='text' AND length(CAST(value AS BLOB)) BETWEEN 1 AND 65536").fetchone()
        if row is None:
            if self.engine.db.execute("SELECT 1 FROM settings WHERE key='best_native_first_execution'").fetchone():
                raise ValueError("NATIVE_FIRST_EXECUTION_RECEIPT_SIZE")
            return None
        record = json.loads(row[0])
        if (not isinstance(record,dict) or not isinstance(record.get("epoch_id"),str)
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}",record["epoch_id"])):
            raise ValueError("NATIVE_FIRST_EXECUTION_RECEIPT_OR_BINDING_CHANGED")
        raw = json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)
        slot = "best_native_first_execution:"+record["epoch_id"]
        audit = self.engine.db.execute("SELECT detail FROM audit WHERE event='NATIVE_FIRST_EXECUTION_AUTHORIZED' "
            "AND json_extract(detail,'$.epoch_id')=? LIMIT 2",(record["epoch_id"],)).fetchall()
        if (record.get("schema") != "OWNER_NATIVE_RESET_FIRST_EXECUTION_R1" or row[0] != raw
                or self.engine.db.execute("SELECT COUNT(*) FROM settings WHERE key=? AND value=?",(slot,raw)).fetchone()[0] != 1
                or len(audit) != 1 or audit[0][0] != raw):
            raise ValueError("NATIVE_FIRST_EXECUTION_RECEIPT_OR_BINDING_CHANGED")
        saved=self.engine._get("best_plan",{})
        if saved.get("metadata",{}).get("signal_date") != record.get("signal_date"):
            if record["epoch_id"] != self._native_reset_record()["reset_id"]:
                raise ValueError("NATIVE_FIRST_EXECUTION_RECEIPT_OR_BINDING_CHANGED")
            return None  # Persisted history grants no authority to a successor signal.
        epoch,bootstrap,saved,current=self._native_first_binding(clock=clock,source=source)
        frozen=saved["metadata"]; capital=self.engine._get("best_capital",{})
        if (record.get("schema") != "OWNER_NATIVE_RESET_FIRST_EXECUTION_R1" or row[0] != raw
                or self.engine.db.execute("SELECT COUNT(*) FROM settings WHERE key=? AND value=?",(slot,raw)).fetchone()[0] != 1
                or len(audit) != 1 or audit[0][0] != raw
                or record.get("epoch_id") != epoch["reset_id"] or record.get("reset_receipt_sha256") != self._content_sha(epoch)
                or record.get("bootstrap_sha256") != self._content_sha(bootstrap)
                or record.get("account_id") != epoch["new_account_id"] or record.get("strategy_id") != self.strategy_id
                or record.get("budget") != self.budget or record.get("unused_cash") != 0 or capital.get("unused_cash") != 0
                or record.get("plan_sha256") != self._content_sha(saved["plan"])
                or record.get("metadata_sha256") != self._content_sha(frozen)
                or record.get("source_archive") != frozen.get("archive")
                or any(record.get(k) != frozen.get(k) for k in ("signal_date","execution_date","next_open_utc","signal_close_utc"))
                or not timestamp(record["authorized_at_utc"]) < timestamp(record["deadline_utc"]) <= timestamp(record["session_close_utc"])
                or (timestamp(record["deadline_utc"])-timestamp(record["authorized_at_utc"])).total_seconds() > 600
                or timestamp(frozen["next_close_utc"]) != timestamp(record["session_close_utc"])
                or current is not None and timestamp(current["next_close_utc"]) != timestamp(record["session_close_utc"])):
            raise ValueError("NATIVE_FIRST_EXECUTION_RECEIPT_OR_BINDING_CHANGED")
        state=self.engine._get("best_execution",{})
        if state and (state.get("signal_date") != record["signal_date"]
                or state.get("native_first_execution_permission_sha256") != self._content_sha(record)):
            raise ValueError("NATIVE_FIRST_EXECUTION_STATE_CHANGED")
        return record

    def authorize_native_first_execution(self, *, authorization_id,requested_at,deadline_utc,expected_strategy_id,
            expected_plan_sha256,expected_source_sha256,expected_reset_receipt_sha256,expected_precondition_sha256,now=None):
        """One explicit native-bootstrap first window; no renewal, start, phase or model side effect."""
        clock=now or self._now()
        request=dict(authorization_id=authorization_id,requested_at=requested_at,deadline_utc=deadline_utc,
            expected_strategy_id=expected_strategy_id,expected_plan_sha256=expected_plan_sha256,
            expected_source_sha256=expected_source_sha256,expected_reset_receipt_sha256=expected_reset_receipt_sha256,
            expected_precondition_sha256=expected_precondition_sha256)
        if (not isinstance(clock,datetime) or clock.tzinfo is None
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{7,79}",str(authorization_id))
                or expected_strategy_id != self.strategy_id
                or any(not isinstance(value,str) or not re.fullmatch(r"[0-9a-f]{64}",value) for value in
                    (expected_plan_sha256,expected_source_sha256,expected_reset_receipt_sha256,expected_precondition_sha256))):
            raise ValueError("NATIVE_FIRST_EXECUTION_REQUEST_INVALID")
        owner=getattr(self,"_maintenance_owner",None)
        with (owner.lock if owner is not None else nullcontext()),self.lock,self.engine.lock:
            prior=self._native_first_record()
            if prior is not None:
                if prior.get("request") != request:
                    raise ValueError("NATIVE_FIRST_EXECUTION_ALREADY_AUTHORIZED_NO_RENEWAL")
                return self._native_first_ack(prior,clock,idempotent=True)
            self._native_reset_require_idle(owner)
            if not clock-timedelta(seconds=60) <= timestamp(requested_at) <= clock:
                raise ValueError("NATIVE_FIRST_EXECUTION_FRESH_REQUEST_REQUIRED")
            epoch,bootstrap,saved,current=self._native_first_binding(clock=clock,source=True)
            frozen=saved["metadata"]; opening=timestamp(current["next_open_utc"]); close=timestamp(current["next_close_utc"])
            deadline=timestamp(deadline_utc); ny=ZoneInfo("America/New_York")
            accounts=[a for a in self.engine.connection.get("accounts",[]) if a.get("market")=="US" and a.get("environment")=="SIMULATE"]
            if (len(accounts)!=1 or str(accounts[0].get("account_id"))!=epoch["new_account_id"]
                    or frozen["execution_date"] != clock.astimezone(ny).date().isoformat()
                    or close.astimezone(ny).date().isoformat() != frozen["execution_date"]
                    or frozen["signal_date"] >= frozen["execution_date"] or timestamp(frozen["signal_close_utc"]) >= opening
                    or not opening <= clock < deadline <= min(clock+timedelta(seconds=600),close)
                    or expected_plan_sha256 != self._content_sha(saved["plan"])
                    or expected_source_sha256 != frozen["archive"]["sha256"]
                    or expected_reset_receipt_sha256 != self._content_sha(epoch)
                    or expected_precondition_sha256 != self._target_alignment_precondition()
                    or self.engine._get("best_execution",{}) != {}
                    or self.engine.db.execute("SELECT 1 FROM orders WHERE mode='moomoo_simulate' AND account_id=? LIMIT 1",(epoch["new_account_id"],)).fetchone()
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("positions") != {}
                    or self.snapshot.get("open_orders") != [] or self.snapshot.get("quotes") != {}
                    or time.monotonic()-self.last_snapshot_at > 60
                    or self.snapshot.get("cash") != self.budget or self.snapshot.get("equity") != self.budget):
                raise ValueError("NATIVE_FIRST_EXECUTION_FRESH_FLAT_OR_TARGET_WINDOW_CHANGED")
            fresh=self._now()
            if fresh < clock or fresh >= deadline or time.monotonic()-self.last_snapshot_at > 60:
                raise ValueError("NATIVE_FIRST_EXECUTION_EXPIRED_DURING_VALIDATION")
            record=dict(schema="OWNER_NATIVE_RESET_FIRST_EXECUTION_R1",request=request,authorization_id=authorization_id,
                epoch_id=epoch["reset_id"],reset_receipt_sha256=self._content_sha(epoch),bootstrap_sha256=self._content_sha(bootstrap),
                account_id=epoch["new_account_id"],strategy_id=self.strategy_id,budget=self.budget,unused_cash=0,
                signal_date=frozen["signal_date"],execution_date=frozen["execution_date"],next_open_utc=frozen["next_open_utc"],
                signal_close_utc=frozen["signal_close_utc"],session_close_utc=close.isoformat(),authorized_at_utc=clock.isoformat(),
                deadline_utc=deadline.isoformat(),plan_sha256=expected_plan_sha256,metadata_sha256=self._content_sha(frozen),
                source_archive=frozen["archive"])
            raw=json.dumps(record,ensure_ascii=False,sort_keys=True,separators=(",", ":"),allow_nan=False)
            with self.engine.db:
                for key in ("best_native_first_execution","best_native_first_execution:"+epoch["reset_id"]):
                    self.engine.db.execute("INSERT INTO settings VALUES (?,?)",(key,raw))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(clock.isoformat(),"NATIVE_FIRST_EXECUTION_AUTHORIZED",raw))
            return self._native_first_ack(record,clock,idempotent=False)

    @staticmethod
    def _native_first_ack(record,clock,*,idempotent):
        return dict(schema=record["schema"],authorization_id=record["authorization_id"],epoch_id=record["epoch_id"],
            signal_date=record["signal_date"],execution_date=record["execution_date"],strategy_id=record["strategy_id"],
            authorized_at_utc=record["authorized_at_utc"],deadline_utc=record["deadline_utc"],
            receipt_sha256=BestBroker._content_sha(record),status="EXPIRED" if clock>=timestamp(record["deadline_utc"]) else "AUTHORIZED",
            idempotent=idempotent,orders_created=0,running=False)

    def _native_first_manifest_guard(self,manifest,clock):
        try: origin=json.loads(manifest.get("source","{}"))
        except (TypeError,ValueError): origin={}
        if not isinstance(origin,dict):origin={}
        if origin.get("published_target_manual_completion_sha256") is not None:
            manual = self._manual_completion_record()
            if manual is not None and manual.get("schema") == "OWNER_NATIVE_CURRENT_MANUAL_COMPLETION_R1":
                return self._manual_manifest_guard(manifest, clock)
        marked=origin.get("native_first_execution_permission_sha256")
        record=self._native_first_record(clock,source=True)
        if record is None:
            if marked is not None:raise ValueError("NATIVE_FIRST_EXECUTION_PERMISSION_REQUIRED")
            return None
        if origin.get("signal_date") != record["signal_date"]:
            raise ValueError("NATIVE_FIRST_EXECUTION_SIGNAL_CHANGED")
        state=self.engine._get("best_execution",{})
        if (marked != self._content_sha(record) or manifest.get("strategy_id") != self.strategy_id
                or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                or origin.get("phase") not in {"SELL","BUY"} or origin.get("budget") != self.budget
                or origin.get("execution_delay_minutes") != 0 or origin.get("execution_window_seconds") != 600
                or any(origin.get(k) != record.get(k) for k in ("next_open_utc","signal_close_utc"))
                or origin.get("source_hash") != (self.plan.get("source_hash") or hashlib.sha256(json.dumps(self.plan["source_refs"],sort_keys=True).encode()).hexdigest())
                or timestamp(manifest["expires_at"]) != timestamp(record["deadline_utc"])
                or not timestamp(record["authorized_at_utc"]) <= clock < timestamp(record["deadline_utc"])
                or clock.astimezone(ZoneInfo("America/New_York")).date().isoformat() != record["execution_date"]
                or state.get("native_first_execution_permission_sha256") != marked
                or state.get("manifest") != manifest or state.get("phase") != origin.get("phase")):
            raise ValueError("NATIVE_FIRST_EXECUTION_MANIFEST_CHANGED_OR_EXPIRED")
        return record

    def _first_execution_book_sha(self):
        return self._content_sha({"cash": self.snapshot.get("cash"),
            "positions": {code: row["qty"] for code, row in self.snapshot.get("positions", {}).items() if row["qty"]}})

    def _first_execution_end(self, now=None, *, allow_closed_source=False):
        if self.strategy_id != SID or self.engine._get("best_strategy_binding", None) is not None:
            return None
        record = self._scoped_legacy_setting("best_first_execution", None)
        if not isinstance(record, dict) or record.get("signal_date") != self.metadata.get("signal_date"):
            return None
        now = now or self._now()
        if self.engine._get("best_first_execution:" + record["signal_date"], None) != record:
            raise ValueError("BEST_FIRST_EXECUTION_IMMUTABLE_PERMISSION_CHANGED")
        saved, capital = self.engine._get("best_plan", {}), self.engine._get("best_capital", {})
        if (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != self.engine._get("best_account", None)
                or str(self.engine.broker.account_id) != self.engine.account_id
                or record.get("budget") != self.budget or capital.get("budget") != self.budget
                or capital.get("account_id") != self.engine.account_id
                or capital.get("unused_cash") != record.get("unused_cash")
                or saved.get("plan") != self.plan
                or _first_execution_sha(saved.get("metadata")) != record.get("frozen_metadata_sha256")
                or not self.allow_partial_quotes):
            raise ValueError("BEST_FIRST_EXECUTION_ACCOUNT_OR_PLAN_CHANGED")
        continuation = self.engine._first_continuation_record("best_first_continuation", record)
        end = self.engine._first_execution_deadline("best_first_continuation", record, plan=self.plan, metadata=saved["metadata"],
            account_id=self.engine.account_id, clock=now, execution_delay_minutes=self.execution_delay_minutes,
            execution_window_seconds=self.execution_window_seconds)
        # Only closed-intent recognition may defer fresh chart-package validation
        # to the original immutable decision archive check. It can never reopen.
        source_record = continuation or record
        if source_record.get("display_binding") is not None or not (allow_closed_source and now >= end):
            from .cohort import Cohort
            current = self.source.status(now=now)
            if source_record.get("display_binding") is not None:
                self._first_execution_display_binding({self.strategy_id: self.plan}, saved["metadata"], current, self.source,
                    account_states={self.strategy_id: saved.get("close_state")},
                    expected=source_record["display_binding"], allow_closed_display=now >= end and not self.engine._pending())
            else:
                Cohort._match_source_refs(record["source_refs"], current, "BEST_FIRST_EXECUTION_SOURCE_CHANGED")
            if (current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or current.get("data_gaps")
                    or any(current.get(key) != saved["metadata"].get(key) for key in
                           ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "next_close_utc"))):
                raise ValueError("BEST_FIRST_EXECUTION_CLOCK_CHANGED")
        state = self.engine._get("best_execution", {})
        if state.get("signal_date") == record["signal_date"]:
            if state.get("first_execution_permission_sha256") != self._content_sha(record):
                raise ValueError("BEST_FIRST_EXECUTION_STATE_CHANGED")
        elif (self._first_execution_book_sha() != record["pre_first_book_sha256"]
                or self.engine.db.execute("SELECT 1 FROM orders WHERE created_at>=? LIMIT 1", (record["next_open_utc"],)).fetchone()):
            raise ValueError("BEST_FIRST_EXECUTION_BASELINE_OR_ATTEMPT_CHANGED")
        if continuation is not None:
            _validate_first_continuation_state(continuation, state)
        return end

    def authorize_first_execution(self, *, execution_date, deadline_utc, authorization_id,
                                  expected_package_sha256, expected_plan_sha256, account_id, now, continuation=None):
        """Authorize one original unstarted SIMULATE plan; no quote/order/start side effect."""
        self._require_legacy_strategy()
        if continuation is not None:
            return self._authorize_first_continuation(execution_date=execution_date, deadline_utc=deadline_utc,
                authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                expected_plan_sha256=expected_plan_sha256, account_id=account_id, now=now, continuation=continuation)
        with self.lock, self.engine.lock:
            self._pending_repair_guard()
            self.engine._require_stopped()
            if (not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                    or self.engine.halt_event.is_set() or self.engine._pending()
                    or not self.allow_partial_quotes or self.execution_delay_minutes != 0
                    or self.execution_window_seconds != 600 or self.budget != 10000
                    or not isinstance(now, datetime) or now.tzinfo is None
                    or not isinstance(authorization_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", authorization_id)
                    or not isinstance(account_id, str) or not account_id
                    or account_id != self.engine._get("best_account", None)
                    or account_id != self.engine.account_id or self.engine.mode != "moomoo_simulate"
                    or self.engine.broker is None or str(self.engine.broker.account_id) != account_id
                    or not any(str(a.get("account_id")) == account_id and a.get("market") == "US"
                               and a.get("environment") == "SIMULATE" for a in self.engine.connection.get("accounts", []))):
                raise ValueError("BEST_FIRST_EXECUTION_REQUIRES_STOPPED_ORIGINAL_SIMULATE_ACCOUNT")
            deadline = timestamp(deadline_utc)
            saved, capital = self.engine._get("best_plan", {}), self.engine._get("best_capital", {})
            plan, metadata = saved.get("plan"), saved.get("metadata", {})
            current = self.source.status(now=now)
            from .cohort import Cohort
            display_binding = self._first_execution_display_binding({self.strategy_id: plan}, metadata, current, self.source,
                account_states={self.strategy_id: saved.get("close_state")})
            refs = metadata.get("source_refs") if display_binding is not None else Cohort._match_source_refs(
                metadata.get("source_refs"), current, "BEST_FIRST_EXECUTION_SOURCE_CHANGED")
            if (metadata.get("execution_date") != execution_date
                    or execution_date != now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    or current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or current.get("data_gaps")
                    or any(current.get(k) != metadata.get(k) for k in
                        ("signal_date", "execution_date", "next_open_utc", "signal_close_utc", "next_close_utc"))
                    or current.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                    or _first_execution_sha(plan) != expected_plan_sha256 or self.plan != plan
                    or capital.get("account_id") != account_id or capital.get("budget") != self.budget
                    or (self._scoped_legacy_setting("best_full_liquidation_reset", {}) or {}).get("stage") not in {None, "COMPLETED"}
                    or any(self.engine._get(k, {}).get("signal_date") == metadata.get("signal_date") for k in
                        ("best_same_day_catchup", "best_same_day_catchup_renewal"))):
                raise ValueError("BEST_FIRST_EXECUTION_REVIEWED_PLAN_CHANGED")
            request = dict(execution_date=execution_date, deadline_utc=deadline.isoformat(),
                authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                expected_plan_sha256=expected_plan_sha256, account_id=account_id)
            prior = self._scoped_legacy_setting("best_first_execution", None)
            if prior is not None and prior.get("signal_date") == metadata.get("signal_date"):
                if prior.get("request") != request:
                    raise ValueError("BEST_FIRST_EXECUTION_ALREADY_AUTHORIZED_NO_RENEWAL")
                self._first_execution_end(now)
                return prior
            state = self.engine._get("best_execution", {})
            if (state.get("signal_date") == metadata.get("signal_date")
                    or self.engine.db.execute("SELECT 1 FROM orders WHERE created_at>=? LIMIT 1", (metadata["next_open_utc"],)).fetchone()
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                    or self.snapshot.get("quotes") != {} or time.monotonic() - self.last_snapshot_at > 60
                    or self.snapshot.get("cash", -1) < capital.get("unused_cash", 0)):
                raise ValueError("BEST_FIRST_EXECUTION_REQUIRES_FRESH_RECONCILED_UNSTARTED_ACCOUNT")
            record = dict(reason="USER_REQUESTED_SAME_DAY_FIRST_EXECUTION", request=request,
                authorization_id=authorization_id, signal_date=metadata["signal_date"], execution_date=metadata["execution_date"],
                account_id=account_id, source_plan_sha256=expected_plan_sha256, source_refs=refs,
                expected_package_sha256=refs["selected/package.json"]["sha256"], authorized_at_utc=now.isoformat(), deadline_utc=deadline.isoformat(),
                next_open_utc=metadata["next_open_utc"], signal_close_utc=metadata["signal_close_utc"], next_close_utc=metadata["next_close_utc"],
                execution_delay_minutes=0, execution_window_seconds=600, budget=self.budget,
                unused_cash=capital["unused_cash"], frozen_metadata_sha256=self._content_sha(metadata),
                pre_first_book_sha256=self._first_execution_book_sha())
            if display_binding is not None:
                record["display_binding"] = display_binding
            _first_execution_end(record, plan=plan, metadata=metadata, account_id=account_id, clock=now,
                execution_delay_minutes=0, execution_window_seconds=600)
            self.engine._store_first_execution_permission("best_first_execution", record)
            self.engine._audit("BEST_FIRST_EXECUTION_AUTHORIZED", self._content_sha(record))
            return record

    def _authorize_first_continuation(self, *, execution_date, deadline_utc, authorization_id,
            expected_package_sha256, expected_plan_sha256, account_id, now, continuation):
        """Record one explicitly reviewed residual lease, preserving the first permit."""
        started = time.monotonic()
        with self.lock, self.engine.lock:
            self._pending_repair_guard()
            self.engine._require_stopped()
            if (not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                    or self.engine.halt_event.is_set() or self.engine._pending()
                    or not self.allow_partial_quotes or self.execution_delay_minutes != 0
                    or self.execution_window_seconds != 600 or self.budget != 10000
                    or not isinstance(now, datetime) or now.tzinfo is None
                    or not isinstance(continuation, dict)
                    or set(continuation) != {"expected_prior_sha256", "expected_execution_sha256"}
                    or self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                    or account_id != self.engine.account_id or account_id != self.engine._get("best_account", None)
                    or str(self.engine.broker.account_id) != account_id
                    or not any(str(a.get("account_id")) == account_id and a.get("market") == "US"
                               and a.get("environment") == "SIMULATE" for a in self.engine.connection.get("accounts", []))):
                raise ValueError("BEST_FIRST_CONTINUATION_REQUIRES_STOPPED_RECONCILED_ORIGINAL_ACCOUNT")
            now, deadline = now.astimezone(timezone.utc), timestamp(deadline_utc)
            prior = self._scoped_legacy_setting("best_first_execution", None)
            saved, capital = self.engine._get("best_plan", {}), self.engine._get("best_capital", {})
            plan, metadata = saved.get("plan"), saved.get("metadata", {})
            state = self.engine._get("best_execution", {})
            current = self.source.status(now=now)
            display = self._first_execution_display_binding({self.strategy_id: plan}, metadata, current, self.source,
                account_states={self.strategy_id: saved.get("close_state")})
            from .cohort import Cohort
            if display is None:
                Cohort._match_source_refs(metadata.get("source_refs"), current, "BEST_FIRST_CONTINUATION_SOURCE_CHANGED")
            request = dict(execution_date=execution_date, deadline_utc=deadline.isoformat(),
                authorization_id=authorization_id, expected_package_sha256=expected_package_sha256,
                expected_plan_sha256=expected_plan_sha256, account_id=account_id, continuation=continuation)
            existing = self.engine._first_continuation_record("best_first_continuation", prior or {})
            if existing is not None:
                if existing.get("request") != request:
                    raise ValueError("BEST_FIRST_CONTINUATION_ALREADY_AUTHORIZED_NO_RENEWAL")
                self._first_execution_end(now)
                return existing
            if (not isinstance(prior, dict) or prior.get("signal_date") != metadata.get("signal_date")
                    or self.engine._get("best_first_execution:" + prior["signal_date"], None) != prior
                    or _first_execution_sha(prior) != continuation["expected_prior_sha256"]
                    or _first_execution_sha(state) != continuation["expected_execution_sha256"]
                    or plan != self.plan or _first_execution_sha(plan) != expected_plan_sha256
                    or _first_execution_sha(metadata) != prior.get("frozen_metadata_sha256")
                    or metadata.get("execution_date") != execution_date
                    or execution_date != now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    or current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or current.get("data_gaps")
                    or current.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                    or any(timestamp(current[k]) != timestamp(metadata[k]) for k in
                           ("next_open_utc", "signal_close_utc", "next_close_utc"))
                    or current.get("signal_date") != metadata.get("signal_date")
                    or current.get("execution_date") != metadata.get("execution_date")
                    or capital.get("account_id") != account_id or capital.get("budget") != self.budget
                    or capital.get("unused_cash") != prior.get("unused_cash")
                    or state.get("phase") not in {"SELL", "BUY"}
                    or state.get("signal_date") != metadata.get("signal_date")
                    or state.get("first_execution_permission_sha256") != _first_execution_sha(prior)
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                    or self.snapshot.get("quotes") != {} or time.monotonic() - self.last_snapshot_at > 60
                    or self.snapshot.get("cash", -1) < capital.get("unused_cash", 0)
                    or any(self.engine._get(k, {}).get("signal_date") == metadata.get("signal_date") for k in
                           ("best_same_day_catchup", "best_same_day_catchup_renewal"))
                    or (self._scoped_legacy_setting("best_full_liquidation_reset", {}) or {}).get("stage") not in {None, "COMPLETED"}):
                raise ValueError("BEST_FIRST_CONTINUATION_REVIEWED_STATE_CHANGED")
            original_end = self._first_execution_end(now, allow_closed_source=True)
            if original_end is None or now < original_end:
                raise ValueError("BEST_FIRST_CONTINUATION_REQUIRES_EXPIRED_FIRST_PERMISSION")
            orders = self.engine.state()["orders"]
            if any(o["status"] not in TERMINAL for o in orders):
                raise ValueError("BEST_FIRST_CONTINUATION_PENDING_OR_UNKNOWN")
            completed = sorted({(o["code"], o["side"]) for o in orders
                if timestamp(o["created_at"]) >= timestamp(metadata["next_open_utc"])
                and o["status"] in {"FILLED", "FILLED_ALL"}})
            allowed = sorted({row["code"] for row in plan["rows"]} | set(self.snapshot.get("positions", {})))
            record = dict(reason="USER_EXPLICIT_ONCE_SAME_DAY_FIRST_CONTINUATION", request=request,
                authorization_id=authorization_id, signal_date=prior["signal_date"], execution_date=execution_date,
                account_id=account_id, prior_permission_sha256=_first_execution_sha(prior),
                source_plan_sha256=expected_plan_sha256, authorized_at_utc=now.isoformat(), deadline_utc=deadline.isoformat(),
                execution_snapshot=deepcopy(state), execution_sha256=_first_execution_sha(state),
                allowed_codes=allowed, completed_pairs=[list(pair) for pair in completed])
            if display is not None:
                record["display_binding"] = display
            _first_continuation_end(record, prior, plan=plan, metadata=metadata, account_id=account_id, clock=now,
                execution_delay_minutes=0, execution_window_seconds=600)
            _validate_first_continuation_state(record, state)
            if now + timedelta(seconds=max(0, time.monotonic() - started)) >= deadline or time.monotonic() - self.last_snapshot_at > 60:
                raise ValueError("BEST_FIRST_CONTINUATION_EXPIRED_DURING_VALIDATION")
            self.engine._store_first_execution_permission("best_first_continuation", record)
            self.engine._audit("BEST_FIRST_CONTINUATION_AUTHORIZED", json.dumps(record, ensure_ascii=False, allow_nan=False))
            return record

    def _automatic_completion(self, now=None):
        """Use the canonical standing projection; no daily grant or old window rewrite."""
        if not self.plan or not self.metadata.get("execution_date"):
            return None
        if not callable(self.engine.automatic_completion_policy_provider):
            return None
        from .applied_source import LEGACY_POLICY
        clock = now or self._now()
        policy = self.engine._automatic_completion_policy(clock, self.strategy_id,
            execution_date=self.metadata["execution_date"])
        if policy is None:
            return None
        opening = timestamp(self.metadata["next_open_utc"])
        closing = timestamp(self.metadata["next_close_utc"])
        signal = self.metadata["signal_date"]
        day = self.metadata["execution_date"]
        ny = ZoneInfo("America/New_York")
        if (not "2026-01-01" <= signal < day < policy["evaluation_end_exclusive"]
                or opening.astimezone(ny).date().isoformat() != day
                or closing.astimezone(ny).date().isoformat() != day
                or closing <= opening + timedelta(seconds=policy["priority_window_seconds"] +
                    policy["close_buffer_seconds"])
                or (not automatic_completion_clock_matches(policy, self.execution_delay_minutes, self.execution_window_seconds)
                    if policy["schema_version"] == 2 else self.execution_delay_minutes not in (0, 30))
                or not self.allow_partial_quotes or self.budget != policy["broker_budget"]
                or self.plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY):
            raise ValueError("AUTOMATIC_COMPLETION_FROZEN_SESSION_CHANGED")
        if policy["schema_version"] == 2:
            return policy, self._scheduled_open(self.metadata["next_open_utc"]) + timedelta(seconds=policy["priority_window_seconds"])
        return policy, closing - timedelta(seconds=policy["close_buffer_seconds"])

    def _execution_end(self):
        """Keep an already-sent signal's original deadline after policy changes."""
        native = self._native_first_record()
        if native is not None:
            return timestamp(native["deadline_utc"])
        manual = self._manual_completion_record()
        if manual is not None:
            return timestamp(manual["deadline_utc"])
        automatic = self._automatic_completion()
        if automatic is not None:
            return automatic[1]
        first = self._first_execution_end()
        if first is not None:
            return first
        catchup = self._catchup_end()
        if catchup is not None:
            return catchup
        opening = self._scheduled_open(self.metadata["next_open_utc"])
        configured = opening + timedelta(seconds=self.execution_window_seconds)
        state = self.engine._get("best_execution", {})
        manifest = state.get("manifest") or {}
        has_signal_order = any(timestamp(order["created_at"]) >= timestamp(self.metadata["next_open_utc"])
                               for order in self._current_session_orders())
        if state.get("signal_date") == self.metadata.get("signal_date") and has_signal_order and not manifest:
            # A cycle with only stale quotes stores manifest=None. The last
            # imported strategy still carries the original submitted deadline.
            row = self.engine.db.execute("SELECT payload FROM strategies WHERE id=?", (self.strategy_id,)).fetchone()
            if row:
                candidate = json.loads(row[0])
                try:
                    origin = json.loads(candidate.get("source", ""))
                except (TypeError, ValueError):
                    origin = {}
                if (candidate.get("strategy_id") == self.strategy_id
                        and origin.get("signal_date") == self.metadata["signal_date"]
                        and origin.get("next_open_utc") == self.metadata["next_open_utc"]):
                    manifest = candidate
        if (state.get("signal_date") == self.metadata.get("signal_date")
                and manifest.get("expires_at") and has_signal_order):
            original = timestamp(manifest["expires_at"])
            if original < configured:
                return original
        return configured

    def _display_execution_end(self):
        """Read the sealed deadline for presentation; never validate current source.

        This result is not execution authority. Tick and submit continue using
        _execution_end/_first_execution_end with the actual clock and source.
        """
        native = self._native_first_record()
        if native is not None:
            return timestamp(native["deadline_utc"])
        record = self._scoped_legacy_setting("best_first_execution", None)
        if not isinstance(record, dict) or record.get("signal_date") != self.metadata.get("signal_date"):
            return self._execution_end()
        saved = self.engine._get("best_plan", {})
        if (self.engine._get("best_first_execution:" + record["signal_date"], None) != record
                or saved.get("plan") != self.plan
                or _first_execution_sha(saved.get("metadata")) != record.get("frozen_metadata_sha256")):
            raise ValueError("BEST_FIRST_EXECUTION_DISPLAY_BINDING_CHANGED")
        # Validate the historical permission with its original grant clock so an
        # expired deadline can still be displayed after restart or on a later day.
        continuation = self.engine._first_continuation_record("best_first_continuation", record)
        return self.engine._first_execution_deadline("best_first_continuation", record, plan=self.plan, metadata=saved["metadata"],
            account_id=self.engine._get("best_account", None), clock=timestamp((continuation or record)["authorized_at_utc"]),
            execution_delay_minutes=self.execution_delay_minutes,
            execution_window_seconds=self.execution_window_seconds)

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
        self.engine.set_limits(self._capital_limits(capital))
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
        lineage = self.engine._get("best_strategy_lineage", [SID])
        if (not isinstance(lineage, list) or not lineage or set(lineage) - set(ACTIVE_PAPER_STRATEGY_IDS)
                or self.strategy_id not in lineage):
            raise ValueError("SIM_STRATEGY_LINEAGE_INVALID")
        marks = ",".join("?" for _ in lineage)
        rows = self.engine.db.execute("SELECT o.code,o.side,f.payload FROM orders o LEFT JOIN order_fills f ON o.id=f.id "
            "WHERE o.strategy_id IN (" + marks + ") AND o.mode='moomoo_simulate' AND o.account_id=?",
            (*lineage, self.engine.account_id))
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

    def _pending_repair_guard(self):
        from .applied_source import _pending_repair_commit_guard
        own = self.engine._get("pending_plan_repair", None)
        peer_path = self.engine.path.parent / "books/cohort.sqlite3"
        peer = None
        if peer_path.is_file():
            with closing(sqlite3.connect(peer_path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
                row = db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
                peer = json.loads(row[0]) if row else None
        if own != peer and (own or peer):
            raise ValueError("PENDING_REPAIR_UNFINISHED_OR_BINDING_CHANGED")
        if own and (Path(own["broker_db"]).resolve() != (self.engine.path / "state.sqlite3").resolve()
                    or Path(own["cohort_db"]).resolve() != peer_path.resolve()):
            raise ValueError("PENDING_REPAIR_DATABASE_OWNER_CHANGED")
        _pending_repair_commit_guard(own)

    def _pending_repair_no_execution(self, request):
        for key in ("best_execution", "best_same_day_catchup"):
            record = self.engine._get(key, {}) or {}
            if record.get("signal_date") == request["signal_date"] or record.get("execution_date") == request["execution_date"]:
                raise ValueError("PENDING_REPAIR_BROKER_EXECUTION_ALREADY_STARTED")
        closing = timestamp(request["signal_close_utc"])
        if any(timestamp(row[0]) >= closing for row in self.engine.db.execute("SELECT created_at FROM orders")):
            raise ValueError("PENDING_REPAIR_BROKER_PERIOD_ORDER_EXISTS")
        for row in self.engine.db.execute("SELECT payload FROM order_fills"):
            record = json.loads(row[0])
            if (record.get("signal_date") == request["signal_date"] or record.get("execution_date") == request["execution_date"]
                    or (record.get("filled_at") and timestamp(record["filled_at"]) >= closing)):
                raise ValueError("PENDING_REPAIR_BROKER_PERIOD_FILL_EXISTS")

    def _pending_repair_actual_book(self):
        before_snapshot, before_time = deepcopy(self.snapshot), self.last_snapshot_at
        try:
            snap = self.engine.broker.snapshot([], include_quotes=False)
            if snap.get("funds_only") is not True or snap.get("quotes") != {} or snap.get("open_orders"):
                raise ValueError("PENDING_REPAIR_FUNDS_ONLY_NO_OPEN_ORDERS_REQUIRED")
            self._accept_snapshot(snap)
            return self._book()
        finally:
            self.snapshot, self.last_snapshot_at = before_snapshot, before_time

    def _pending_repair_prepare(self, request, metadata, clock):
        """Read actual held quantities; preparation never persists a plan or sends an order."""
        from .applied_source import LEGACY_POLICY, _pending_source_binding, _reference, _json, _state
        self.engine._require_stopped()
        if (not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                or self.engine.halt_event.is_set() or self.engine._pending()
                or self.execution_delay_minutes != 0 or self.execution_window_seconds != 600
                or self.allow_partial_quotes is not True):
            raise ValueError("PENDING_REPAIR_BROKER_NOT_STOPPED_OR_POLICY_CHANGED")
        account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
        saved = self.engine._get("best_plan", None)
        reset = self._scoped_legacy_setting("best_full_liquidation_reset", {}) or {}
        if (not saved or reset.get("stage") not in (None, "COMPLETED")
                or self.engine.mode != "moomoo_simulate" or self.engine.account_id != account
                or not account or capital.get("account_id") != account or capital.get("budget") != self.budget
                or self.engine.broker is None or str(self.engine.broker.account_id) != account):
            raise ValueError("PENDING_REPAIR_ORIGINAL_SIMULATE_ACCOUNT_REQUIRED")
        frozen, plan = saved.get("metadata", {}), saved.get("plan", {})
        if (any(frozen.get(key) != metadata.get(key) for key in
                ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                or any(frozen.get("source_refs", {}).get(key) != metadata.get("source_refs", {}).get(key)
                       for key in ("selected/package.json", "frozen_calendar", "session_hours_rules"))
                or plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY
                or plan.get("signal_date") != request["signal_date"]
                or plan.get("execution_date") != request["execution_date"]
                or plan.get("valuation_basis") != "SIGNAL_CLOSE" or plan.get("reset_id") or plan.get("execution_mode")
                or any(frozen.get(key) != expected for key, expected in
                       (("execution_delay_minutes", 0), ("execution_window_seconds", 600), ("allow_partial_quotes", True))
                       if key in frozen)
                or any(self.engine._get(key, None) != expected for key, expected in
                       (("execution_delay_minutes", 0), ("execution_window_seconds", 600), ("allow_partial_quotes", True)))):
            raise ValueError("PENDING_REPAIR_BROKER_NORMAL_LEGACY_PLAN_REQUIRED")
        self._pending_repair_no_execution(request)
        archive = frozen.get("archive")
        if not isinstance(archive, dict):
            raise ValueError("PENDING_REPAIR_BROKER_ARCHIVE_REQUIRED")
        _reference(archive["path"], archive["sha256"])
        old = _json(archive["path"])
        if old.get("plans", {}).get(self.strategy_id) != plan or old.get("source_refs") != frozen.get("source_refs"):
            raise ValueError("PENDING_REPAIR_BROKER_ARCHIVE_CHANGED")
        book = self._pending_repair_actual_book()
        books = {self.strategy_id: book}
        states = self.source.close_states(books, signal_date=request["signal_date"])
        if (set(states) != {self.strategy_id} or _state(states[self.strategy_id], request["signal_date"])
                != _state(saved.get("close_state"), request["signal_date"])):
            raise ValueError("PENDING_REPAIR_BROKER_ACTUAL_CLOSE_STATE_CHANGED")
        scoped = {**request, "previous_archive": archive}
        loaded = self.source.load(states, now=clock, repair_request=scoped)
        _pending_source_binding(loaded, frozen, request["expected_package_sha256"], clock)
        if set(loaded.get("plans", {})) != {self.strategy_id}:
            raise ValueError("PENDING_REPAIR_BROKER_STRATEGY_CHANGED")
        new_metadata = {key: deepcopy(value) for key, value in loaded.items() if key != "plans"}
        new_metadata.update(execution_delay_minutes=0, execution_window_seconds=600, allow_partial_quotes=True)
        return {"metadata": new_metadata, "plan": deepcopy(loaded["plans"][self.strategy_id]), "close_state": states[self.strategy_id]}, book


    def authorize_manual_residual_sell(self, *, execution_date, deadline_utc, authorization_id,
            code, target_qty, max_sell_qty, limit_price, max_spread_bps, spread_authorization,
            expected_prior_sha256, expected_plan_sha256, expected_execution_sha256,
            expected_package_sha256, now):
        """One compact separate human permit; old catchup/renewal bytes remain intact."""
        self._require_legacy_strategy()
        with self.lock:
            self.engine._require_stopped()
            if (not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                    or self.engine._pending() or self.engine.halt_event.is_set()
                    or not isinstance(now, datetime) or now.tzinfo is None
                    or not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", authorization_id)
                    or not code_valid(code) or type(target_qty) is not int or target_qty < 0
                    or type(max_sell_qty) is not int or not 1 <= max_sell_qty <= 1000000
                    or type(max_spread_bps) is not int or max_spread_bps not in {50, 60}
                    or spread_authorization != ("ORIGINAL_50BP" if max_spread_bps == 50 else "USER_EXPLICIT_SINGLE_SELL_60BP")
                    or any(not isinstance(v, str) or not re.fullmatch(r"[0-9a-f]{64}", v) for v in
                        (expected_prior_sha256, expected_plan_sha256, expected_execution_sha256, expected_package_sha256))):
                raise ValueError("MANUAL_RESIDUAL_SELL_REQUIRES_STOPPED_RECONCILED_ORIGINAL_ACCOUNT")
            limit_price = number(limit_price, "人工卖出最低限价", .000001)
            now, deadline = now.astimezone(timezone.utc), timestamp(deadline_utc)
            saved, state = self.engine._get("best_plan", {}), self.engine._get("best_execution", {})
            prior = self._scoped_legacy_setting("best_same_day_catchup", {})
            renewal = self.engine._get("best_same_day_catchup_renewal", {})
            plan, metadata = saved.get("plan"), saved.get("metadata", {})
            account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
            request = dict(execution_date=execution_date, deadline_utc=deadline.isoformat(), authorization_id=authorization_id,
                code=code, target_qty=target_qty, max_sell_qty=max_sell_qty, limit_price=limit_price,
                max_spread_bps=max_spread_bps, spread_authorization=spread_authorization,
                expected_prior_sha256=expected_prior_sha256, expected_plan_sha256=expected_plan_sha256,
                expected_execution_sha256=expected_execution_sha256, expected_package_sha256=expected_package_sha256)
            existing = self.engine._get("best_manual_residual_sell:" + str(metadata.get("signal_date")), None)
            if existing is not None:
                if any(existing.get(k) != v for k, v in request.items()):
                    raise ValueError("MANUAL_RESIDUAL_SELL_ALREADY_AUTHORIZED_NO_RENEWAL")
                return existing
            current = self.source.status(now=now)
            from .cohort import Cohort
            Cohort._match_source_refs(metadata.get("source_refs"), current, "MANUAL_RESIDUAL_SELL_SOURCE_CHANGED")
            self._catchup_renewal(prior, state, plan=plan, metadata=metadata, renewal=renewal)
            resolved = prior.get("deferred_sell_targets", {})
            buy = state if state.get("phase") == "BUY" else state.get("resume_buy_state", {})
            held = self.snapshot.get("positions", {}).get(code, {}).get("qty", 0)
            if (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                    or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                    or capital.get("account_id") != account or capital.get("budget") != self.budget
                    or not isinstance(plan, dict) or metadata.get("execution_date") != execution_date
                    or execution_date != now.astimezone(ZoneInfo("America/New_York")).date().isoformat()
                    or any(current.get(k) != metadata.get(k) for k in ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                    or current.get("data_gaps") or current.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                    or not renewal or renewal.get("signal_date") != metadata.get("signal_date")
                    or code not in renewal.get("allowed_codes", []) or code in buy.get("processed_codes", [])
                    or self._content_sha(renewal) != expected_prior_sha256
                    or self._content_sha(plan) != expected_plan_sha256 or self._content_sha(state) != expected_execution_sha256
                    or metadata.get("source_refs", {}).get("selected/package.json", {}).get("sha256") != expected_package_sha256
                    or resolved.get(code) != target_qty or held - target_qty != max_sell_qty
                    or self.snapshot.get("funds_only") is not True or self.snapshot.get("open_orders") != []
                    or time.monotonic() - self.last_snapshot_at > 60
                    or not timestamp(renewal["deadline_utc"]) <= now < deadline <= min(now + timedelta(seconds=600), timestamp(metadata["next_close_utc"]))):
                raise ValueError("MANUAL_RESIDUAL_SELL_FROZEN_TARGET_ACCOUNT_OR_TIME_CHANGED")
            for row in self.engine.db.execute("SELECT * FROM orders WHERE mode='moomoo_simulate' AND account_id=? AND code=? AND created_at>=?",
                    (account, code, metadata["next_open_utc"])):
                if row["status"] != "CANCELLED_BEFORE_SEND" or row["order_id"] is not None:
                    raise ValueError("MANUAL_RESIDUAL_SELL_ORIGINAL_CODE_ALREADY_ATTEMPTED")
                fill = self.engine.db.execute("SELECT 1 FROM order_fills WHERE id=?", (row["id"],)).fetchone()
                if fill:
                    raise ValueError("MANUAL_RESIDUAL_SELL_ORIGINAL_CODE_HAS_FILL_EVIDENCE")
            grant = dict(request, schema_version=1, reason="USER_EXPLICIT_ONCE_MANUAL_RESIDUAL_SELL",
                signal_date=metadata["signal_date"], account_id=account, budget=self.budget,
                unused_cash=capital["unused_cash"], authorized_at_utc=now.isoformat(),
                source_refs_sha256=self._content_sha(metadata["source_refs"]))
            with self.engine.db:
                raw = json.dumps(grant, ensure_ascii=False, allow_nan=False)
                self.engine.db.execute("INSERT INTO settings VALUES (?,?)", ("best_manual_residual_sell:" + metadata["signal_date"], raw))
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_manual_residual_sell", raw))
                self.engine.db.execute("INSERT INTO settings VALUES (?,?)", ("best_manual_residual_sell_state:" + authorization_id,
                    json.dumps({"status": "AUTHORIZED"}, ensure_ascii=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(), "BEST_MANUAL_RESIDUAL_SELL_AUTHORIZED", raw))
            return grant

    def execute_manual_residual_sell(self, authorization_id, *, now):
        """One stopped synchronous call through the original ledger and Engine.step."""
        self._require_legacy_strategy()
        with self.lock:
            self.engine._require_stopped()
            grant = self.engine._get("best_manual_residual_sell", {})
            if (not self.stop_event.is_set() or (self.worker and self.worker.is_alive())
                    or grant.get("authorization_id") != authorization_id or self.engine.halt_event.is_set()):
                raise ValueError("MANUAL_RESIDUAL_SELL_REQUIRES_STOPPED_ORIGINAL_PERMIT")
            existing = [dict(row) for row in self.engine.db.execute(
                "SELECT * FROM orders WHERE strategy_id=? AND mode='moomoo_simulate' AND account_id=? AND code=? AND created_at>=?",
                (self.strategy_id, grant["account_id"], grant["code"], grant["authorized_at_utc"]))
                if row["status"] != "CANCELLED_BEFORE_SEND" or row["order_id"] is not None]
            if existing:
                return {"status": "ORDER_ALREADY_CREATED", "orders": existing}
            saved = self.engine._get("best_plan", {})
            current = self.source.status(now=now)
            from .cohort import Cohort
            Cohort._match_source_refs(saved["metadata"].get("source_refs"), current, "MANUAL_RESIDUAL_SELL_SOURCE_CHANGED")
            manifest = dict(schema_version=1, strategy_id=self.strategy_id, name="HGB 对角风险 · 本次人工剩余卖出",
                revision=grant["signal_date"] + ":manual-sell:" + authorization_id,
                asof=grant["authorized_at_utc"], expires_at=grant["deadline_utc"], provenance="live",
                targets=[{"code": grant["code"], "target_qty": grant["target_qty"]}],
                source=json.dumps({"kind": "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN", "phase": "SELL",
                    "signal_date": grant["signal_date"], "manual_residual_sell_permission_sha256": self._content_sha(grant)}, ensure_ascii=False))
            self.engine._manual_residual_sell_permission(manifest, now)
            self.engine.import_strategy(manifest)
            self.engine.switch(self.strategy_id)
            self.engine.cancel_step.clear()
            previous_cancel = self.engine.broker.cancel_check
            # Automatic scheduling stays stopped; manual cancellation still uses the original engine events.
            self.engine.broker.cancel_check = lambda: self.engine.halt_event.is_set() or self.engine.cancel_step.is_set()
            try:
                result = self.engine.step(respect_cancel=True, allow_partial_quotes=True, broker_order_type="NORMAL")
                self.engine._set("best_manual_residual_sell_state:" + authorization_id,
                    {"status": "PENDING_RECONCILE" if result["submitted"] else "WAITING_QUOTES"})
                return result
            finally:
                self.engine.broker.cancel_check = previous_cancel
                self.engine.cancel_step.set()


    def _reconcile_manual_residual_sell(self, snapshot):
        """Finish only from this permit's actual full fill and account snapshot; never send."""
        if self.strategy_id != SID or self.engine._get("best_strategy_binding", None) is not None:
            return None
        grant = self.engine._get("best_manual_residual_sell", {})
        completed = self.engine._get("best_manual_residual_sell_state:" + str(grant.get("authorization_id")), {})
        refining = completed.get("status") == "COMPLETED" and completed.get("execution_complete") is False
        if not grant or (completed.get("status") == "COMPLETED" and not refining):
            return False
        if self.engine._pending() or snapshot.get("funds_only") is not True or snapshot.get("open_orders") != []:
            return False
        if self.engine._get("best_execution", {}).get("signal_date") != grant.get("signal_date"):
            return False  # A later ordinary signal is never edited by an old manual permit.
        code = grant["code"]
        if snapshot.get("positions", {}).get(code, {}).get("qty", 0) != grant["target_qty"]:
            return False
        with self.engine.lock:
            raw_state = self.engine.db.execute("SELECT value FROM settings WHERE key='best_execution'").fetchone()[0]
            raw_plan = self.engine.db.execute("SELECT value FROM settings WHERE key='best_plan'").fetchone()[0]
            state = json.loads(raw_state)
            original_state = None
            if refining:
                # The old receipt has no output-state SHA. Invert only the known
                # one-code cleanup, and require the original signed SHA exactly.
                audit = self.engine.db.execute("SELECT detail FROM audit WHERE event=? AND time=?",
                    ("BEST_MANUAL_RESIDUAL_SELL_RECONCILED", completed.get("reconciled_at_utc")))
                if (completed.get("grant_sha256") != self._content_sha(grant)
                        or not any(self._content_sha(json.loads(r[0])) == self._content_sha(completed) for r in audit)
                        or state.get("phase") != "BUY"):
                    return False
                prior = self._scoped_legacy_setting("best_same_day_catchup", {})
                renewal = self.engine._get("best_same_day_catchup_renewal", {})
                frozen = renewal.get("execution_snapshot", {})
                sources = (state, prior.get("original_execution", {}), frozen.get("resume_buy_state", frozen))
                for deferred_source in sources:
                    for skipped_source in sources:
                        candidate = deepcopy(state)
                        candidate["processed_codes"] = [c for c in candidate.get("processed_codes", []) if c != code]
                        for field, source in (("deferred_sells", deferred_source), ("skipped", skipped_source)):
                            candidate[field] = [r for r in state.get(field, []) if r.get("code") != code] + [
                                deepcopy(r) for r in source.get(field, []) if r.get("code") == code]
                        if self._content_sha(candidate) == grant["expected_execution_sha256"]:
                            original_state = candidate
                            break
                    if original_state is not None:
                        break
                if original_state is None:
                    return False  # Never infer an unknown preimage or replace the signed CAS.
            manifest = self.engine._manifest()
            if self.engine._manual_residual_sell_permission(manifest, self._now(), completion_only=True,
                    completion_execution_state=original_state) != grant:
                return False
            identity = json.dumps(["moomoo_simulate", grant["account_id"], self.strategy_id, manifest["asof"], code])
            order_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
            row = self.engine.db.execute(
                "SELECT o.*,f.payload AS fill FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
                "WHERE o.id=? AND o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=? "
                "AND o.code=? AND o.side='SELL' AND o.order_type='NORMAL'",
                (order_id, self.strategy_id, grant["account_id"], code)).fetchone()
            if (row is None or row["status"] not in {"FILLED_ALL", "FILLED"} or not row["order_id"]
                    or not timestamp(grant["authorized_at_utc"]) <= timestamp(row["created_at"]) < timestamp(grant["deadline_utc"])):
                return False
            fill = json.loads(row["fill"]) if row["fill"] else {}
            if (type(fill.get("fill_qty")) is not int or not 0 < fill["fill_qty"] == row["qty"] == grant["max_sell_qty"]
                    or fill.get("fill_source") != "MOOMOO_SIMULATE_ORDER_RECONCILE"
                    or number(fill.get("fill_price"), "券商实际成交均价", .000001) <= 0):
                return False
            if refining and (completed.get("order_id") != order_id or completed.get("fill_qty") != fill["fill_qty"]
                    or completed.get("actual_target_qty") != grant["target_qty"]):
                return False
            if not refining and self._content_sha(state) != grant["expected_execution_sha256"]:
                raise ValueError("MANUAL_RESIDUAL_SELL_COMPLETION_EXECUTION_CHANGED")
            updated = deepcopy(state)
            buy = updated if updated.get("phase") == "BUY" else updated.get("resume_buy_state")
            if not isinstance(buy, dict):
                raise ValueError("MANUAL_RESIDUAL_SELL_COMPLETION_BUY_STATE_REQUIRED")
            processed = set(buy.get("processed_codes", [])) | {code}
            buy["processed_codes"] = sorted(processed)
            for branch in (updated, buy):
                branch["processed_codes"] = sorted(set(branch.get("processed_codes", [])) | {code})
                branch["deferred_sells"] = [r for r in branch.get("deferred_sells", []) if r.get("code") != code]
                branch["skipped"] = [r for r in branch.get("skipped", []) if r.get("code") != code]
            prior = self._scoped_legacy_setting("best_same_day_catchup", {})
            required = (set(buy.get("target_quantities", {})) | set(prior.get("eligible_codes", []))
                        | set(prior.get("deferred_sell_targets", {})) | set(prior.get("resolved_buy_targets", {}))
                        | {r["code"] for r in prior.get("original_execution", {}).get("deferred_sells", [])})
            exits = set()
            weights = {r["code"]: r["target_weight"] for r in json.loads(raw_plan)["plan"]["rows"]}
            for exit_code in sorted(required - processed):
                if (buy.get("target_quantities", {}).get(exit_code) != 0
                        or exit_code not in weights or weights[exit_code] != 0
                        or snapshot.get("positions", {}).get(exit_code, {}).get("qty", 0) != 0):
                    continue
                rows = self.engine.db.execute("SELECT o.qty,o.status,o.order_id,f.payload FROM orders o "
                    "LEFT JOIN order_fills f ON f.id=o.id WHERE o.strategy_id=? AND o.mode='moomoo_simulate' "
                    "AND o.account_id=? AND o.code=? AND o.side='SELL' AND o.created_at>=? AND o.created_at<?",
                    (self.strategy_id, grant["account_id"], exit_code, timestamp(json.loads(raw_plan)["metadata"]["next_open_utc"]).isoformat(),
                     timestamp(json.loads(raw_plan)["metadata"]["next_close_utc"]).isoformat()))
                for quantity, status, broker_id, payload in rows:
                    evidence = json.loads(payload) if payload else {}
                    if (status in {"FILLED_ALL", "FILLED"} and broker_id and type(evidence.get("fill_qty")) is int
                            and 0 < evidence["fill_qty"] == quantity
                            and evidence.get("fill_source") == "MOOMOO_SIMULATE_ORDER_RECONCILE"
                            and evidence.get("fill_price") is not None and evidence["fill_price"] > 0):
                        exits.add(exit_code)
                        break
            done = required.issubset(processed | exits) and not buy.get("deferred_sells") and not buy.get("skipped")
            if refining and not done:
                return False
            if done:
                # Resume the original BUY bookkeeping, retaining its fixed quantities and original manifest.
                updated = deepcopy(buy)
                updated.update(phase="DONE", completion_status="EXECUTED")
            completion = dict(status="COMPLETED", reconciled_at_utc=self._now().isoformat(),
                grant_sha256=self._content_sha(grant), order_id=order_id, fill_qty=fill["fill_qty"],
                actual_target_qty=grant["target_qty"], execution_complete=done, sell_exit_codes=sorted(exits))
            with self.engine.db:
                changed = self.engine.db.execute("UPDATE settings SET value=? WHERE key='best_execution' AND value=? "
                    "AND EXISTS(SELECT 1 FROM settings WHERE key='best_plan' AND value=?)",
                    (json.dumps(updated, ensure_ascii=False), raw_state, raw_plan)).rowcount
                if changed != 1:
                    raise ValueError("MANUAL_RESIDUAL_SELL_COMPLETION_CAS_CHANGED")
                self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",
                    ("best_manual_residual_sell_state:" + grant["authorization_id"], json.dumps(completion, ensure_ascii=False)))
                self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",
                    (completion["reconciled_at_utc"], "BEST_MANUAL_RESIDUAL_SELL_RECONCILED", json.dumps(completion, ensure_ascii=False)))
            return True

    def cancel_manual_residual_sell(self, authorization_id, *, now):
        self._require_legacy_strategy()
        self.engine.cancel_step.set()
        with self.lock:
            grant = self.engine._get("best_manual_residual_sell", {})
            if grant.get("authorization_id") != authorization_id:
                raise ValueError("MANUAL_RESIDUAL_SELL_PERMISSION_ID_CHANGED")
            self.engine._set("best_manual_residual_sell_state:" + authorization_id,
                {"status": "CANCELLED", "at": now.isoformat()})
            return {"authorization_id": authorization_id, "status": "CANCELLED", "sent_orders_preserved": True}

    def start(self):
        owner = getattr(self, "_maintenance_owner", None)
        if owner is not None:
            owner._maintenance_start_guard()
        with self.lock:
            requested = self.engine._get("best_next_ordinary_execution_clock", None) or {}
            next_pair = (requested.get("execution_delay_minutes", self.execution_delay_minutes),
                requested.get("execution_window_seconds", self.execution_window_seconds))
            provider = self.engine.automatic_completion_policy_provider
            policy = provider() if callable(provider) else None
            if (next_pair == (25, 1500) and policy is not None and policy.get("enabled")
                    and self.strategy_id in policy.get("active_strategy_ids", [])
                    and not automatic_completion_clock_matches(policy, 25, 1500)):
                raise ValueError("ORDINARY_CLOCK_SCHEMA2_POLICY_UPDATE_REQUIRED")
            self._pending_repair_guard()
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
        owner = getattr(self, "_maintenance_owner", None)
        if owner is not None and getattr(owner, "_maintenance_stopping_thread", None) != threading.get_ident():
            owner._maintenance_user_stop()
        self.stop_event.set()
        self.engine.stop()
        with self.lock:
            self.status = "STOPPED"
            self.reason = "暂停新委托；已发送模拟委托继续核对"

    def halt(self):
        self.stop_event.set()
        self.engine.cancel_step.set()
        owner = getattr(self, "_maintenance_owner", None)
        if owner is not None:
            owner._maintenance_user_stop()
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
                self._reconcile_manual_residual_sell(snapshot)
                target_acknowledged = self._acknowledge_resolved_target_completion(self._now())
                self.engine._audit("BEST_RECONCILE_SYNCED", json.dumps({
                    "previous_last_error": previous_error, "receipt_count": len(results),
                    "pending_order_count": len(self.engine._pending()),
                    "automatic_execution_paused": True, "halt_preserved": self.engine.halt_event.is_set(),
                    "valuation_basis": "BROKER_ACCOUNT_METADATA"}, ensure_ascii=False))
                self.last_error = ""
                self.engine._set("best_last_error", "")
                self.status = "HALTED" if self.engine.halt_event.is_set() else "STOPPED"
                self.reason = "已同步券商真实成交与持仓；自动执行仍暂停"
                if target_acknowledged:
                    self.reason += "; 已确认冻结目标全部完成，未发出新委托"
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
                if self.status in {"WAITING_QUOTES", "RETRY_COOLDOWN"} and not self.engine._pending():
                    wait_seconds = 10
            except Exception as exc:
                with self.lock:
                    source_busy = self._source_validation_pending and str(exc) == "CANONICAL_SOURCE_WORKER_BUSY"
                    self.status = ("WAITING_SOURCE" if source_busy else
                        (("PENDING_RECONCILE" if self.engine._pending() else "WAITING_QUOTES")
                         if isinstance(exc, BrokerReadError) else "BLOCKED"))
                    self.last_error = str(exc)
                    self.reason = ("原输入验证暂忙；保留已验证计划，暂停新委托并等待短暂重试" if source_busy else self.last_error)
                    if source_busy:
                        wait_seconds = max(1, self._source_retry_at - time.monotonic())
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

    def _require_manual_preparation(self):
        if (not self.manual_data_updates or not self.stop_event.is_set()
                or self.worker and self.worker.is_alive() or self.engine.halt_event.is_set()
                or self.engine._pending()):
            raise ValueError("MANUAL_CACHE_PREPARATION_REQUIRES_PAUSED_IDLE_OWNERS")
        self.engine._require_stopped()
        self._pending_repair_guard()
        self._require_original_manual_account()

    def _require_original_manual_account(self):
        account, capital = self.engine._get("best_account", None), self.engine._get("best_capital", {})
        if (self.engine.mode != "moomoo_simulate" or self.engine.broker is None
                or self.engine.account_id != account or str(self.engine.broker.account_id) != account
                or capital.get("account_id") != account or capital.get("budget") != self.budget):
            raise ValueError("MANUAL_CACHE_PREPARATION_REQUIRES_ORIGINAL_ACCOUNT_RECONCILE")

    def prepare_published_inputs(self, *, expected_signal_date, now=None):
        """Prepare the original SIM account from published inputs without a send cycle."""
        from .cohort import Cohort
        with self.lock:
            clock = now or self._now()
            self._require_manual_preparation()
            data = self.source.status(now=clock)
            signal, execution, _ = Cohort._metadata(self, data, clock)
            if (signal != expected_signal_date or data.get("source_date") != signal or data.get("data_gaps")
                    or data.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}):
                raise ValueError("MANUAL_CACHE_CURRENT_PUBLISHED_SOURCE_REQUIRED")
            self._accept_snapshot(self.engine.broker.snapshot([], include_quotes=False))
            self._native_reset_preparing_origin = self._native_reset_bootstrap_origin(clock)
            try:
                self._prepare(clock, prepare_only=True, expected_signal_date=signal)
            finally:
                self._native_reset_preparing_origin = None
            self._require_manual_preparation()
            prepared = bool(self.plan and self.metadata.get("signal_date") == signal
                and self.metadata.get("status") in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                and not self.metadata.get("data_gaps"))
            receipt = dict(action="PREPARE_CURRENT_PUBLISHED_INPUTS", strategy_id=self.strategy_id,
                signal_date=signal, execution_date=execution, status="READY" if prepared else self.status,
                prepared=prepared, reason=self.reason, orders_created=0, running=not self.stop_event.is_set())
            self.engine._audit("MANUAL_PUBLISHED_INPUTS_PREPARED", json.dumps(receipt, ensure_ascii=False))
            return receipt

    def _require_running(self):
        owner = getattr(self, "_maintenance_owner", None)
        if owner is not None and owner._maintenance_active():
            raise ValueError("MANUAL_MAINTENANCE_ACTIVE")
        if self.stop_event.is_set() or self.engine.halt_event.is_set():
            raise ValueError("模拟策略已停止，禁止新委托")

    def _book(self):
        capital = self.engine._get("best_capital", {})
        return {"cash": self.snapshot.get("cash", 0) - capital.get("unused_cash", 0),
                "positions": {code: p["qty"] for code, p in self.snapshot.get("positions", {}).items()}}

    def _recoverable_close_error(self):
        error = self.last_error
        prefix = "QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:"
        return (isinstance(error, str) and error.startswith(prefix)
                and code_valid("US." + error[len(prefix):])
                and self.engine._get("best_last_error", "") == error)

    def _clear_prepared_close_error(self, states):
        state = states.get(self.strategy_id, {}) if isinstance(states, dict) else {}
        if (not self._recoverable_close_error() or not self.plan or self._cancelled() or self.engine._pending()
                or not isinstance(states, dict) or set(states) != {self.strategy_id}
                or state.get("signal_date") != self.metadata.get("signal_date")
                or state.get("valuation_basis") != "SIGNAL_CLOSE"
                or self.metadata.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                or self.metadata.get("data_gaps")):
            return
        self.engine._audit("SOURCE_PREPARATION_RECOVERED", json.dumps({
            "previous_error": self.last_error, "signal_date": self.metadata["signal_date"],
            "execution_date": self.metadata.get("execution_date")}, ensure_ascii=False))
        self.engine._set("best_last_error", "")
        self.last_error = ""

    def _prepare(self, now, *, prepare_only=False, expected_signal_date=None):
        """Commit readiness on success; a busy owner pauses sends, not its plan."""
        from .applied_source import DailySourceError
        previous = (self.plan, self.metadata, self.prepared_at, self._closed_current_signal)
        self._source_validation_pending = False
        try:
            if prepare_only:
                self._prepare_current(now, prepare_only=True, expected_signal_date=expected_signal_date)
            else:
                self._prepare_current(now)
        except DailySourceError as exc:
            if str(exc) == "CANONICAL_SOURCE_WORKER_BUSY":
                self.plan, self.metadata, self.prepared_at, self._closed_current_signal = previous
                self._source_validation_pending = True
                self._source_retry_at = time.monotonic() + 5
                self.status, self.reason = "WAITING_SOURCE", "原输入验证暂忙；保留已验证计划，暂停新委托并等待短暂重试"
            else:
                self.plan = None
            raise
        except Exception:
            self.plan = None
            raise
        else:
            self._source_retry_at = 0.0
            if self.last_error == "CANONICAL_SOURCE_WORKER_BUSY":
                self.last_error = ""
                self.engine._set("best_last_error", "")

    def _source_send_ready(self, now):
        """Revalidate the frozen owner immediately before a new send/amendment."""
        expected_plan = self._content_sha(self.plan)
        expected_clock = {key: self.metadata.get(key) for key in
            ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")}
        self._prepare(now)
        if (not self.plan or self._content_sha(self.plan) != expected_plan
                or any(self.metadata.get(key) != value for key, value in expected_clock.items())
                or self.metadata.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                or self.metadata.get("data_gaps")):
            return False  # Rebuild through the next ordinary cycle; never send the old manifest.
        clock = self._now()
        opening = self._scheduled_open(self.metadata["next_open_utc"])
        if clock < opening or clock >= self._execution_end():
            return False
        self._require_running()
        return True

    def _prepare_current(self, now, *, prepare_only=False, expected_signal_date=None):
        from .cohort import Cohort, _manual_inference_update
        require = self._require_manual_preparation if prepare_only else self._require_running
        self.prepared_at = time.monotonic()
        self._closed_current_signal = False
        require()
        reset = self._scoped_legacy_setting("best_full_liquidation_reset", None)
        if reset:
            saved = self.engine._get("best_plan", None)
            if not saved:
                raise ValueError("RESET_FROZEN_PLAN_REQUIRED")
            if reset.get("stage") != "COMPLETED":
                self.plan, self.metadata = saved["plan"], saved["metadata"]
                self._active_full_reset()
                self.status, self.reason = "WAITING_OPEN", "按已冻结目标等待清仓后重买窗口"
                return
        self.plan = None  # Any failed source read/preparation leaves no cached target for a subsequent tick.
        metadata = Cohort._book_source_data(self.strategy_id, self.source.status(now=now))
        self.metadata = metadata
        day = metadata.get("signal_date") or metadata.get("latest_completed_signal_date")
        if prepare_only and day != expected_signal_date:
            raise ValueError("MANUAL_CACHE_CURRENT_PUBLISHED_SOURCE_REQUIRED")
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
            if self.strategy_id not in LEGACY_PAPER_STRATEGY_IDS and metadata.get("candidate_source_scope") == "PAPER_CANDIDATE_REFS_V1":
                Cohort._match_source_refs(saved["plan"].get("source_refs"), metadata,
                    "PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED")
            repair = self.engine._get("pending_plan_repair", None)
            if repair and repair.get("signal_date") == day:
                from .applied_source import _reference, _json, _state
                self._pending_repair_guard()
                frozen = saved["metadata"]
                current, original = metadata.get("source_refs"), frozen.get("source_refs")
                if (metadata.get("status") not in {"READY", "OPEN_WINDOW", "MISSED_OPEN"} or metadata.get("data_gaps")
                        or any(metadata.get(key) != frozen.get(key) for key in
                               ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
                        or not isinstance(current, dict) or not current or not isinstance(original, dict)
                        or any(key not in original or original[key] != value for key, value in current.items())):
                    raise ValueError("PENDING_REPAIR_BROKER_FROZEN_SOURCE_CHANGED")
                archive = repair["broker_archive"]
                _reference(archive["path"], archive["sha256"])
                archived = _json(archive["path"])
                if (archived.get("plans", {}).get(self.strategy_id) != saved["plan"] or archived.get("source_refs") != original
                        or archived.get("states", {}).get(self.strategy_id) != _state(saved["close_state"], day)):
                    raise ValueError("PENDING_REPAIR_BROKER_FROZEN_ARCHIVE_CHANGED")
                self.plan, self.metadata = deepcopy(saved["plan"]), deepcopy(frozen)
                return
            published_target = (saved["plan"].get("execution_mode") == "REBALANCE_EXISTING_POSITIONS"
                or saved["metadata"].get("execution_mode") == "REBALANCE_EXISTING_POSITIONS"
                or any(entry.get("cancellation", {}).get("published_target_rebalance", {}).get("signal_date") == day
                       for entry in self.engine._get("best_reset_archive", {}).values()))
            if published_target:
                try:
                    self._published_target_receipt(saved["plan"], saved["metadata"])
                    closed = self._closed_execution(saved, now)
                    checked = metadata
                    if closed and metadata.get("source_refs", {}).get("selected/package.json") != saved["metadata"].get("source_refs", {}).get("selected/package.json"):
                        self._closed_history_binding({self.strategy_id: saved["plan"]}, saved["metadata"], metadata, saved["metadata"]["archive"])
                        checked = deepcopy(metadata)
                        checked["source_refs"]["selected/package.json"] = deepcopy(saved["metadata"]["source_refs"]["selected/package.json"])
                    self._published_target_binding(saved["plan"], saved["metadata"], checked)
                    self._closed_current_signal = closed
                except Exception:
                    self.plan = None  # A later tick cannot bypass a failed preparation during its 60-second cache.
                    raise
            self.plan = saved["plan"]
            self.metadata = {**saved["metadata"], **{k: metadata[k] for k in
                ("status", "reason", "ready", "execute_now", "next_expected_open_utc", "next_refresh_utc", "refresh_not_before_utc", "next_close_utc", "now_utc") if k in metadata}}
            if reset and day == reset.get("signal_date"):
                self.metadata = saved["metadata"]
                self._active_full_reset()
            self.status = self.metadata.get("status", "BLOCKED")
            self.reason = self.metadata.get("reason", "等待下一开盘")
            if (not published_target and self._recoverable_close_error() and self.plan
                    and self.metadata.get("status") in {"READY", "OPEN_WINDOW", "MISSED_OPEN"}
                    and not self.metadata.get("data_gaps")):
                # A saved plan alone cannot prove a formerly missing close is
                # available. Revalidate through the original read-only source;
                # never replace its frozen plan, close state or execution state.
                current_refs, frozen_refs = metadata.get("source_refs"), self.metadata.get("source_refs")
                if (isinstance(current_refs, dict) and current_refs and isinstance(frozen_refs, dict)
                        and all(key in frozen_refs and frozen_refs[key] == value for key, value in current_refs.items())):
                    require()
                    checked = self.source.close_states({self.strategy_id: self._book()}, signal_date=day)
                    require()
                    state = checked.get(self.strategy_id, {}) if isinstance(checked, dict) else {}
                    close_refs = state.get("source_refs")
                    if (not isinstance(checked, dict) or set(checked) != {self.strategy_id} or state.get("signal_date") != day
                            or state.get("valuation_basis") != "SIGNAL_CLOSE"
                            or not isinstance(close_refs, dict)
                            or any(key not in close_refs or close_refs[key] != value for key, value in current_refs.items())):
                        raise ValueError("RECOVERED_CLOSE_SOURCE_BINDING_MISMATCH")
                    self._clear_prepared_close_error(checked)
            return
        if self.manual_data_updates and not prepare_only:
            self.status, self.reason = "WAITING_MANUAL_UPDATE", "等待每日手动更新并准备原模拟账户目标；保留现仓和历史成交"
            return
        require()
        conversion = self._target_conversion()
        if conversion is not None:
            if prepare_only:
                self._continue_target_conversion(conversion, metadata, now, prepare_only=True)
            else:
                self._continue_target_conversion(conversion, metadata, now)
            return
        book = self._book()
        states = self.source.close_states({self.strategy_id: book}, signal_date=day)
        states[self.strategy_id]["units"] = {code.removeprefix("US."): qty for code, qty in book["positions"].items()}
        if self.strategy_id == "R7_GROSS_LINEAR":
            requested = self.engine._get("best_requested_strategy_state", {}).get(self.strategy_id, {})
            states[self.strategy_id]["previous_requested_gross"] = requested_gross_input(requested, day)
        require()
        with _manual_inference_update(self, self.source) if prepare_only else nullcontext():
            result = self.source.load(states, now=now)
        if prepare_only and any(result.get(key) != metadata.get(key) for key in
                ("signal_date", "execution_date", "next_open_utc", "signal_close_utc")):
            raise ValueError("MANUAL_CACHE_SOURCE_CHANGED_DURING_PREPARATION")
        scoped = Cohort._book_source_data(self.strategy_id, result)
        self.metadata = {k: v for k, v in scoped.items() if k != "plans"}
        self.plan = result.get("plans", {}).get(self.strategy_id)
        self.status = result.get("status", "BLOCKED")
        self.reason = result.get("reason", "等待下一开盘")
        if not self.plan:
            detail = result.get("strategy_status", {}).get(self.strategy_id, {})
            self.status, self.reason = detail.get("status", "BLOCKED"), detail.get("reason", "本策略冻结目标暂不可用")
        if self.plan:
            next_clock = self._next_ordinary_clock(day)
            requested = self.engine._get("best_requested_strategy_state", {})
            if self.strategy_id == "R7_GROSS_LINEAR":
                requested[self.strategy_id] = accepted_requested_gross_state(self.plan, states[self.strategy_id], day)
            with self.engine.db:
                for key, value in (("best_plan", {"metadata": self.metadata, "plan": self.plan, "close_state": states[self.strategy_id]}),
                        ("best_requested_strategy_state", requested)):
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False, allow_nan=False)))
                self._persist_native_reset_bootstrap()
                if next_clock is not None:
                    for key in ("execution_delay_minutes", "execution_window_seconds"):
                        self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(next_clock[key])))
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", ("best_next_ordinary_execution_clock", "null"))
                    self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)", (now.isoformat(),
                        "ORDINARY_EXECUTION_CLOCK_APPLIED", json.dumps({**next_clock, "signal_date": day}, sort_keys=True)))
            if next_clock is not None:
                self.execution_delay_minutes = next_clock["execution_delay_minutes"]
                self.execution_window_seconds = next_clock["execution_window_seconds"]
            if not metadata.get("data_gaps"):
                self._clear_prepared_close_error(states)

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
        if any(w < 0 or w > (.100001 if self.strategy_id == SID else 1.000001) for w in weights.values()) or sum(weights.values()) > 1.000001:
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
        holds = exact_hold_units(self.plan)
        for code in codes:
            qty = snap["positions"].get(code, {}).get("qty", 0)
            if code in holds:
                if qty != holds[code]:
                    raise ValueError("EXACT_HOLD_UNITS_CHANGED")
                continue
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
        manifest = dict(schema_version=1, strategy_id=self.strategy_id, name=APPLIED_STRATEGY_NAMES[self.strategy_id] + " · MOOMOO 模拟",
            revision=f"{day}:{phase}", asof=now.isoformat(), expires_at=end.isoformat(), provenance="live",
            targets=targets, source=json.dumps({"kind": "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN",
                "signal_date": day, "signal_close_utc": self.metadata.get("signal_close_utc"),
                "next_open_utc": self.metadata["next_open_utc"],
                "execution_time_utc": execution_at.isoformat(),
                "execution_delay_minutes": self.execution_delay_minutes,
                "source_hash": self.plan.get("source_hash") or hashlib.sha256(json.dumps(self.plan.get("source_refs", self.metadata.get("source_refs", {})), sort_keys=True).encode()).hexdigest(),
                "budget": self.budget, "phase": phase, "research_broker_action_allowed": False}, ensure_ascii=False))
        self.engine.import_strategy(manifest)
        self.engine.switch(self.strategy_id)
        state = {"signal_date": day, "phase": phase, "manifest": manifest}
        self.engine._set("best_execution", state)
        return state

    @staticmethod
    def _desired_quantity(weight, equity, quote, *, buy):
        reserve = 1.005 * MARKET_BUY_CASH_BUFFER if buy else 1.005
        return math.floor(weight * equity / (quote["ask"] * reserve) / quote["lot_size"]) * quote["lot_size"]

    def _current_session_orders(self, *, descending=True):
        """Scope physical account/strategy first; compare aware instants before reading fill JSON."""
        opening=timestamp(self.metadata["next_open_utc"])
        closing=timestamp(self.metadata["next_close_utc"]) if self.metadata.get("next_close_utc") is not None else None
        rows=self.engine.db.execute("SELECT rowid AS scoped_rowid,* FROM orders WHERE strategy_id=? AND mode='moomoo_simulate' AND account_id=?",
            (self.strategy_id,self.engine.account_id))
        selected=[]
        for row in rows:
            item=dict(row);ordinal=item.pop("scoped_rowid")
            try:instant=timestamp(item["created_at"])
            except (TypeError,ValueError,OverflowError) as exc:
                raise ValueError("CURRENT_SESSION_ORDER_TIMESTAMP_INVALID") from exc
            if instant<opening or closing is not None and instant>=closing:continue
            selected.append((instant,ordinal,item))
        selected.sort(key=lambda value:value[:2],reverse=descending)
        result=[]
        for _,_,item in selected:
            fill=self.engine.db.execute("SELECT payload FROM order_fills WHERE id=?",(item["id"],)).fetchone()
            payload=fill[0] if fill else None
            result.append({**(json.loads(payload) if payload else {}),**item})
        return result

    def _foreign_processed_scope_repair(self, previous, orders, weights, holds, now):
        """Prove only a native bootstrap BUY's impossible processed-without-quantity markers."""
        if (previous.get("phase")!="BUY" or previous.get("signal_date")!=self.metadata.get("signal_date")
                or self.engine.db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_epoch'").fetchone() is None):
            return None
        candidates=set(previous.get("processed_codes",[]))-set(previous.get("target_quantities",{}))-set(holds)
        candidates={code for code in candidates if weights.get(code,0)>0}
        candidates.difference_update(row["code"] for row in orders)
        if not candidates:return None
        opening=timestamp(self.metadata["next_open_utc"])
        closing=timestamp(self.metadata["next_close_utc"]) if self.metadata.get("next_close_utc") is not None else None
        placeholders=",".join("?" for _ in candidates)
        own=self.engine.db.execute("SELECT code,created_at FROM orders WHERE mode='moomoo_simulate' AND account_id=? AND code IN ("+placeholders+")",
            [self.engine.account_id,*sorted(candidates)])
        for row in own:
            try:instant=timestamp(row["created_at"])
            except (TypeError,ValueError,OverflowError) as exc:
                raise ValueError("CURRENT_SESSION_ORDER_TIMESTAMP_INVALID") from exc
            if instant>=opening and (closing is None or instant<closing):candidates.discard(row["code"])
        if not candidates:return None
        placeholders=",".join("?" for _ in candidates)
        query="SELECT id,created_at,strategy_id,mode,account_id,code,side,status FROM orders WHERE mode='moomoo_simulate' "
        query+="AND side='BUY' AND code IN ("+placeholders+") AND account_id!=?"
        args=[*sorted(candidates),self.engine.account_id]
        matched=[]
        for ordinal,row in enumerate(self.engine.db.execute(query+" ORDER BY rowid",args)):
            if row["status"] not in TERMINAL-{"CANCELLED_BEFORE_SEND"}:continue
            try:instant=timestamp(row["created_at"])
            except (TypeError,ValueError,OverflowError) as exc:
                raise ValueError("FOREIGN_SESSION_ORDER_TIMESTAMP_INVALID") from exc
            if instant>=opening and (closing is None or instant<closing):matched.append((instant,ordinal,dict(row)))
        evidence=[value[2] for value in sorted(matched,key=lambda value:value[:2])]
        if not evidence:return None
        epoch,bootstrap,saved,_=self._native_first_binding(clock=now,source=True)
        native=self._native_first_record(now)
        permitted_start=max(opening,timestamp(native["authorized_at_utc"])) if native is not None else opening
        permitted_end=timestamp(native["deadline_utc"]) if native is not None else self._execution_end()
        if (not bootstrap or self.strategy_id!=epoch["target_strategy_id"] or self.engine.account_id!=epoch["new_account_id"]
                or self.plan!=saved.get("plan") or self._content_sha(self.plan)!=bootstrap["plan_sha256"]
                or previous["signal_date"]!=saved.get("metadata",{}).get("signal_date")
                or self.engine._pending() or self.engine.halt_event.is_set() or now<permitted_start or now>=permitted_end):
            raise ValueError("NATIVE_PROCESSED_SCOPE_REPAIR_REQUIRES_CURRENT_VALID_EXECUTION")
        return dict(schema="NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIR_R1",epoch_id=epoch["reset_id"],
            account_id=self.engine.account_id,strategy_id=self.strategy_id,signal_date=previous["signal_date"],phase="BUY",
            plan_sha256=self._content_sha(self.plan),original_execution_sha256=self._content_sha(previous),
            original_processed_codes=previous.get("processed_codes",[]),
            original_target_quantities_sha256=self._content_sha(previous.get("target_quantities",{})),
            removed_processed_codes=sorted({row["code"] for row in evidence}),foreign_attempts=evidence)

    def _partial_execution(self, now, phase, snap, deferred_sells=None, sell_codes=None, resume_buy_state=None):
        """Build only quote-qualified targets; preserve original weights and each first resolved quantity."""
        day = self.metadata["signal_date"]
        previous = self.engine._get("best_execution", {})
        automatic = self._automatic_completion(now)
        frozen_sells = dict(previous.get("resolved_sell_targets", {})) if automatic else {}
        if automatic and previous.get("phase") == "SELL":
            frozen_sells.update(previous.get("resolved_sell_targets", {}))
        if automatic and resume_buy_state is not None:
            frozen_sells.update(resume_buy_state.get("resolved_sell_targets", {}))
        reset = self._active_full_reset()
        if reset and phase == "BUY" and not reset.get("post_liquidation_baseline"):
            raise ValueError("RESET_LIQUIDATION_NOT_CONFIRMED")
        if reset and phase == "SELL" and reset.get("post_liquidation_baseline") is not None:
            raise ValueError("RESET_SELL_AFTER_LIQUIDATION_FORBIDDEN")
        if previous.get("signal_date") != day or previous.get("phase") != phase:
            previous = {}
        if phase == "SELL":
            sell_codes = sell_codes if sell_codes is not None else previous.get("sell_codes")
            resume_buy_state = resume_buy_state if resume_buy_state is not None else previous.get("resume_buy_state")
        quantities = dict(previous.get("target_quantities", {}))
        if automatic and phase == "SELL":
            quantities.update(frozen_sells)
        remainder = self._scoped_legacy_setting("best_same_day_catchup", None)
        remainder_sells = None
        same_day_remainder = isinstance(remainder, dict) and remainder.get("signal_date") == day
        quote_refresh = same_day_remainder and remainder.get("quote_refresh") is True
        original_sell_stage = same_day_remainder and remainder.get("original_sell_stage") is True
        if original_sell_stage:
            self._catchup_end()
            quantities.update(remainder["resolved_sell_targets"] if phase == "SELL" else remainder["resolved_buy_targets"])
            if phase == "SELL" and sell_codes is None:
                sell_codes = remainder["original_sell_codes"]
        else:
            if (isinstance(remainder, dict) and remainder.get("include_deferred_sells") is True
                    and remainder.get("signal_date") == day):
                self._catchup_end()  # Validate the durable original BUY / authorized SELL detour.
                remainder_sells = remainder["deferred_sell_targets"]
                if quote_refresh:
                    quantities.update(remainder.get("resolved_buy_targets", {}) if phase == "BUY" else {})
                if phase == "SELL":
                    if sell_codes is None or not set(sell_codes).issubset(
                            {row["code"] for row in remainder["original_execution"]["deferred_sells"]}
                            if quote_refresh else remainder_sells):
                        raise ValueError("REMAINDER_SELL_CODES_CHANGED")
                    quantities.update({code: remainder_sells[code] for code in sell_codes if code in remainder_sells})
                else:
                    # The original SELL quantity also binds its first resumed BUY resolution.
                    # A changed price cannot turn this remainder into a reverse repurchase.
                    quantities.update(remainder.get("deferred_buy_targets", remainder_sells))
        renewal = self._catchup_renewal(remainder, self.engine._get("best_execution", {})) if same_day_remainder else None
        new_details = {}
        processed = set(previous.get("processed_codes", []))
        weights = {row["code"]: float(row["target_weight"]) for row in self.plan.get("rows", [])}
        holds = exact_hold_units(self.plan)
        if any(snap["positions"].get(code, {}).get("qty", 0) != qty for code, qty in holds.items()):
            raise ValueError("EXACT_HOLD_UNITS_CHANGED")
        processed.update(holds)
        if any(not math.isfinite(weight) or not 0 <= weight <= (.100001 if self.strategy_id == SID else 1.000001) for weight in weights.values()) or sum(weights.values()) > 1.000001:
            raise ValueError("HGB 对角风险目标超出冻结仓位约束")
        capital = self.engine._get("best_capital", {})
        cash = snap["cash"] - capital["unused_cash"]
        equity = cash + sum(position["market_value"] for position in snap["positions"].values())
        if cash < 0 or equity <= 0:
            raise ValueError("独立模拟策略预算已不足，禁止使用其余模拟现金")
        self.engine.set_limits(dict(max_order_notional=equity * 2, max_daily_turnover=equity * 4,
            max_position_notional=equity * 2, max_total_exposure=equity * 2,
            min_cash_reserve=capital["unused_cash"]))
        if automatic:
            # Read this account/session only; avoid materializing historical audits/fills.
            rows = self.engine.db.execute("SELECT o.*,f.payload FROM orders o LEFT JOIN order_fills f ON f.id=o.id "
                "WHERE o.strategy_id=? AND o.mode='moomoo_simulate' AND o.account_id=? "
                "AND o.created_at>=? AND o.created_at<? ORDER BY o.created_at,o.rowid",
                (self.strategy_id, self.engine.account_id, timestamp(self.metadata["next_open_utc"]).isoformat(),
                 timestamp(self.metadata["next_close_utc"]).isoformat()))
            orders = []
            for row in rows:
                item = dict(row); payload = item.pop("payload")
                orders.append({**item, **(json.loads(payload) if payload else {})})
        else:
            orders = self._current_session_orders()
        scope_repair = self._foreign_processed_scope_repair(previous,orders,weights,holds,now) if phase == "BUY" else None
        if scope_repair is not None:
            processed.difference_update(scope_repair["removed_processed_codes"])
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
        if quote_refresh and not original_sell_stage:
            codes.intersection_update(remainder["eligible_codes"])
            if phase == "BUY":
                # Unresolved SELL quotes still block this ticker. Resolved increases may BUY;
                # a resolved decrease may only finish SELL and cannot reverse direction.
                pending_deferred = {row["code"] for row in remainder["original_execution"]["deferred_sells"]} - set(remainder_sells)
                codes.difference_update(pending_deferred)
        if renewal is not None:
            codes.intersection_update(renewal["allowed_codes"])
        for code in sorted(codes, key=lambda code: (-weights.get(code, 0), code)):
            qty = snap["positions"].get(code, {}).get("qty", 0)
            if reset and phase == "SELL":
                quantities[code] = 0
            attempts = attempts_by_code.get((code, phase), [])
            prior = attempts[-1] if attempts else None
            if prior:
                terminal_buy = (phase == "BUY" and prior["status"] in
                                {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                                and qty < quantities.get(code, qty))
                terminal_sell = (automatic is not None and phase == "SELL"
                    and prior["status"] in {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                    and code in quantities and qty > quantities[code])
                if automatic is not None and (terminal_buy or terminal_sell):
                    try:
                        capacity = self.engine._terminal_retry_remaining(code, phase,
                            self.metadata["next_open_utc"], self.metadata["next_close_utc"], self.strategy_id)
                        residual = (quantities[code] - qty) if terminal_buy else (qty - quantities[code])
                        if residual > capacity:
                            raise ValueError("TERMINAL_RETRY_ACTUAL_RESIDUAL_EXCEEDS_NATIVE_REMAINING")
                    except ValueError as exc:
                        processed.discard(code)
                        skipped.append(dict(code=code, reason=str(exc)))
                        continue
                if terminal_buy or terminal_sell:
                    if automatic is None and len(attempts) > MAX_TERMINAL_RETRIES_PER_CODE:
                        processed.add(code)
                    else:
                        observed_at = cooldowns.get(prior["id"])
                        if not observed_at:
                            observed_at = now.isoformat()
                            cooldowns[prior["id"]] = observed_at
                            cooldowns_changed = True
                        if (now - timestamp(observed_at)).total_seconds() < TERMINAL_RETRY_COOLDOWN_SECONDS:
                            processed.discard(code)
                            skipped.append(dict(code=code, reason=("原卖单已确认终结；冷却后仅补原目标差额" if terminal_sell
                                else "原买单已确认失败；冷却后按最新合格报价重试"),
                                                retry_after_utc=(timestamp(observed_at) + timedelta(seconds=TERMINAL_RETRY_COOLDOWN_SECONDS)).isoformat()))
                            continue
                        processed.discard(code)
                        retry_generations[code] = len(attempts)
                else:
                    processed.add(code)
            if automatic and phase == "BUY" and code in frozen_sells:
                if qty > frozen_sells[code]:
                    processed.discard(code)
                    row = dict(code=code, reason="等待原已定SELL目标完成，禁止反向BUY")
                    skipped.append(row)
                    if not any(r.get("code") == code for r in deferred):
                        deferred.append(row)
                    continue
                processed.add(code)  # A fixed decrease cannot reverse into an intraday repurchase.
            manual_decrease = (quote_refresh
                and any(row["code"] == code and row["phase"] == "SELL" and row["desired"] < row["held_before"]
                        for row in remainder.get("new_quantity_records", [])))
            if phase == "BUY" and remainder_sells is not None and code in remainder_sells and (not quote_refresh or manual_decrease):
                if qty > remainder_sells[code]:
                    raise ValueError("REMAINDER_ORIGINAL_SELL_NOT_COMPLETED")
                processed.add(code)  # Continue the original SELL, never create a new BUY for it.
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
            spread_ok = (auto_completion_spread_is_valid(quote) if automatic is not None
                and automatic[0]["one_tick_spread"] else spread <= self.engine.limits["max_spread_bps"])
            if not spread_ok or abs(price / quote["price"] - 1) > .02:
                skipped.append(dict(code=code, reason="真实盘口价差或价格偏离超过原执行限制"))
                continue
            if quote_refresh or automatic is not None:
                age = (now - timestamp(quote["asof"])).total_seconds()
                if not 0 <= age <= min(30, self.engine.limits["max_quote_age_seconds"]) or quote.get("tradable") is not True:
                    skipped.append(dict(code=code, reason="真实行情过期或证券不可交易；不建立人工新数量"))
                    continue
            if code not in quantities:
                # MARKET has no execution-price ceiling. Keep extra strategy
                # cash uncommitted when sizing new BUY intents.
                buy_reserve = 1.005 * MARKET_BUY_CASH_BUFFER
                desired = self._desired_quantity(weights.get(code, 0), equity, quote, buy=(phase == "BUY" or (quote_refresh and not original_sell_stage)))
                if phase == "SELL":
                    quantities[code] = min(desired, qty)
                    new_details[code] = dict(held_before=qty, desired=desired, new_sell_target=quantities[code], new_buy_target=desired)
                else:
                    affordable = math.floor(max(0, cash) / (quote["ask"] * buy_reserve) / quote["lot_size"]) * quote["lot_size"]
                    quantities[code] = max(qty, min(desired, qty + affordable))
                    new_details[code] = dict(held_before=qty, desired=desired, new_buy_target=quantities[code])
                    if desired > quantities[code]:
                        skipped.append(dict(code=code, reason="可用策略现金不足，保留原目标权重及未买入差额", cash_limited=True))
            target = quantities[code]
            if automatic and phase == "SELL" and target < qty:
                frozen_sells[code] = target
            if phase == "BUY" and (code in retry_generations or self._catchup_end() is not None):
                affordable = math.floor(max(0, cash) / (quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER) / quote["lot_size"]) * quote["lot_size"]
                cap = math.floor(weights[code] * equity / (quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER) / quote["lot_size"]) * quote["lot_size"]
                target = max(qty, min(target, qty + affordable, cap))
            if phase == "BUY":
                cash -= max(0, target - qty) * quote["ask"] * 1.005 * MARKET_BUY_CASH_BUFFER
            if target == qty or (phase == "SELL" and remainder_sells is not None and qty < target):
                processed.add(code)  # A completed SELL must never turn into a BUY.
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
            manifest = dict(schema_version=1, strategy_id=self.strategy_id, name=APPLIED_STRATEGY_NAMES[self.strategy_id] + " · MOOMOO 模拟",
                revision=f"{day}:{phase}", asof=prior_manifest.get("asof", previous.get("phase_asof", now.isoformat())),
                expires_at=end.isoformat(), provenance="live", targets=targets,
                source=json.dumps(dict(kind="AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN", signal_date=day,
                    signal_close_utc=self.metadata["signal_close_utc"], next_open_utc=self.metadata["next_open_utc"],
                    execution_time_utc=self._scheduled_open(self.metadata["next_open_utc"]).isoformat(),
                    execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds,
                    source_hash=source_hash, budget=self.budget, phase=phase,
                    retry_generations={code: retry_generations.get(code, 0) for code in (target["code"] for target in targets)},
                    allow_partial_quotes=True, research_broker_action_allowed=False), ensure_ascii=False))
            manual = self._manual_completion_record()
            if manual is not None:
                origin = json.loads(manifest["source"])
                origin.update(published_target_manual_completion_sha256=self._content_sha(manual), manual_id=manual["manual_id"])
                manifest["source"] = json.dumps(origin,ensure_ascii=False)
            if automatic is not None:
                origin = json.loads(manifest["source"])
                origin.update(automatic_completion_policy_sha256=_first_execution_sha(automatic[0]),
                    automatic_completion_plan_sha256=_first_execution_sha(self.plan),
                    automatic_completion_source_refs_sha256=_first_execution_sha(self.metadata.get("source_refs")),
                    next_close_utc=self.metadata["next_close_utc"], execution_date=self.metadata["execution_date"])
                manifest["source"] = json.dumps(origin, ensure_ascii=False)
            if quote_refresh:
                manifest["asof"] = remainder["authorized_at_utc"]
                origin = json.loads(manifest["source"])
                origin.update(manual_remainder_intent=remainder["reason"],
                              manual_authorized_at_utc=remainder["authorized_at_utc"])
                manifest["source"] = json.dumps(origin, ensure_ascii=False)
            first = self._scoped_legacy_setting("best_first_execution", None)
            if isinstance(first, dict) and first.get("signal_date") == day:
                self._first_execution_end(now)
                origin = json.loads(manifest["source"])
                origin["first_execution_permission_sha256"] = self._content_sha(first)
                continuation = self.engine._first_continuation_record("best_first_continuation", first)
                if continuation is not None:
                    origin["first_continuation_permission_sha256"] = self._content_sha(continuation)
                manifest["source"] = json.dumps(origin, ensure_ascii=False)
            if reset:
                origin = json.loads(manifest["source"])
                origin.update(reset_id=reset["reset_id"], execution_mode="FULL_LIQUIDATION_THEN_REBUY")
                manifest["source"] = json.dumps(origin, ensure_ascii=False)
            native = self._native_first_record()
            if native is not None:
                origin = json.loads(manifest["source"])
                origin["native_first_execution_permission_sha256"] = self._content_sha(native)
                manifest["source"] = json.dumps(origin,ensure_ascii=False)
            self.engine.import_strategy(manifest)
            self.engine.switch(self.strategy_id)
        state = dict(signal_date=day, phase=phase, manifest=manifest,
            phase_asof=previous.get("phase_asof", prior_manifest.get("asof", now.isoformat())),
            target_quantities=quantities, processed_codes=sorted(processed), skipped=skipped,
            retry_generations=retry_generations,
            deferred_sells=deferred, original_target_weights=weights,
            valuation_basis="BROKER_ACCOUNT_METADATA", original_target_cash_weight=self.plan["target_cash_weight"])
        native = self._native_first_record()
        if native is not None:
            state["native_first_execution_permission_sha256"] = self._content_sha(native)
        if automatic is not None:
            state["resolved_sell_targets"] = frozen_sells
            state["automatic_completion_policy_sha256"] = _first_execution_sha(automatic[0])
        first = self._scoped_legacy_setting("best_first_execution", None)
        if isinstance(first, dict) and first.get("signal_date") == day:
            state["first_execution_permission_sha256"] = self._content_sha(first)
            continuation = self.engine._first_continuation_record("best_first_continuation", first)
            if continuation is not None:
                state["first_continuation_permission_sha256"] = self._content_sha(continuation)
        if phase == "SELL" and resume_buy_state is not None:
            state.update(sell_codes=sorted(sell_codes), resume_buy_state=resume_buy_state)
        if isinstance(first, dict) and first.get("signal_date") == day and continuation is not None:
            _validate_first_continuation_state(continuation, state)
        if original_sell_stage:
            self._persist_original_sell_execution(remainder, state, now, snap, phase, new_details)
        elif quote_refresh:
            self._persist_manual_execution(remainder, state, now, snap, phase, new_details)
        else:
            if scope_repair is None:
                self.engine._set("best_execution", state)
            else:
                state["account_scope_repair_sha256"] = self._content_sha(scope_repair)
                with self.engine.db:
                    self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)",("best_execution",json.dumps(state,ensure_ascii=False,allow_nan=False)))
                    self.engine.db.execute("INSERT INTO audit VALUES (?,?,?)",(now.isoformat(),"NATIVE_EXECUTION_ACCOUNT_SCOPE_REPAIRED",json.dumps(scope_repair,ensure_ascii=False,allow_nan=False)))
        return state

    def _tick_partial(self, now):
        previous = self.engine._get("best_execution", {})
        day = self.metadata["signal_date"]
        reset = self._active_full_reset()
        if previous.get("signal_date") == day and previous.get("phase") == "DONE":
            self.status = previous.get("completion_status", "EXECUTED")
            self.reason = "本信号已处理；保留实际成交与未成交明细，不重复发送"
            return
        codes = {row["code"] for row in self.plan.get("rows", []) if row["target_weight"]}
        codes.update(self.snapshot.get("positions", {}))
        remainder = self._scoped_legacy_setting("best_same_day_catchup", None)
        is_remainder = (isinstance(remainder, dict) and remainder.get("include_deferred_sells") is True
                        and remainder.get("signal_date") == day)
        original_sell_stage = is_remainder and remainder.get("original_sell_stage") is True
        if original_sell_stage:
            self._remainder_binding(remainder, previous)
            codes.intersection_update(remainder["eligible_codes"])
        else:
            if is_remainder:
                self._remainder_binding(remainder, previous)
                buy = previous if previous.get("phase") == "BUY" else previous["resume_buy_state"]
                codes = {row["code"] for row in self.plan["rows"] if row["target_weight"]
                         and row["code"] not in buy.get("processed_codes", [])}
                if remainder.get("quote_refresh") is True:
                    codes.intersection_update(remainder["eligible_codes"])
                    codes.update(row["code"] for row in remainder["original_execution"]["deferred_sells"])
                else:
                    codes.update(remainder["deferred_sell_targets"])
                codes.update(row["code"] for row in self._current_session_orders()
                             if timestamp(row["created_at"]) >= timestamp(self.metadata["next_open_utc"])
                             and row["side"] == "BUY" and row["status"] in {"FAILED", "CANCELLED_ALL", "CANCELLED_PART"}
                             and (remainder.get("quote_refresh") is not True or row["code"] in remainder["eligible_codes"]))
        renewal = self._catchup_renewal(remainder, previous) if is_remainder else None
        if renewal is not None:
            codes.intersection_update(renewal["allowed_codes"])
        snap = self.engine.broker.snapshot_partial(sorted(codes))
        self._require_running()
        self._accept_snapshot(snap)
        if is_remainder or reset or self._native_first_record() is not None or self._manual_completion_record() is not None or self._automatic_completion(now) is not None or self._first_execution_end(now) is not None:
            now = self._now()  # Recheck the actual clock after the synchronous quote batch.
            if now >= self._execution_end():
                self.status = "PARTIALLY_EXECUTED"
                self.reason = "当日人工补执行窗口已结束；保留实际成交及未完成目标，不发新单"
                return
        phase = previous.get("phase", "SELL") if previous.get("signal_date") == day else "SELL"
        if reset and reset.get("post_liquidation_baseline") is not None:
            if phase != "BUY" and any(item.get("qty", 0) for item in snap["positions"].values()):
                raise ValueError("RESET_REBUY_STATE_MISSING_WITH_POSITIONS")
            phase = "BUY"  # A crash after the cash baseline may resume BUY, never liquidate new holdings.
            if previous.get("deferred_sells"):
                raise ValueError("RESET_REBUY_DEFERRED_SELL_FORBIDDEN")
        if phase == "BUY" and previous.get("deferred_sells"):
            sell_codes = {row["code"] for row in previous["deferred_sells"]}
            state = self._partial_execution(now, "SELL", snap, sell_codes=sell_codes, resume_buy_state=previous)
            phase = "SELL"
        else:
            state = self._partial_execution(now, phase, snap)
        if phase == "SELL" and not state["manifest"]:
            if reset and not self._finish_reset_liquidation(reset, snap, now):
                self.status = "BLOCKED" if any(row.get("already_attempted") for row in state["skipped"]) else "WAITING_QUOTES"
                self.reason = "全量清仓尚未由真实成交确认；保留剩余持仓，禁止进入重买"
                return
            if (is_remainder and remainder.get("quote_refresh") is True and not original_sell_stage
                    and state.get("resume_buy_state") is not None):
                pending = [code for code, target in remainder["deferred_sell_targets"].items()
                           if code in codes and code in state.get("sell_codes", [])
                           and code not in state["processed_codes"]
                           and snap["positions"].get(code, {}).get("qty", 0) > target]
                if pending:
                    self.status = "WAITING_QUOTES"
                    self.reason = "等待合格真实报价完成已解析卖出目标: " + ", ".join(sorted(pending))
                    return
            if self._automatic_completion(now) is not None:
                waiting = [code for code, target in state.get("resolved_sell_targets", {}).items()
                           if snap["positions"].get(code, {}).get("qty", 0) > target]
                if waiting:
                    self.status = "RETRY_COOLDOWN" if any(r.get("retry_after_utc") for r in state["skipped"]) else "WAITING_QUOTES"
                    self.reason = "等待原SELL目标完成后继续BUY: " + ", ".join(sorted(waiting))
                    return
            deferred = [row for row in state["skipped"] if row["code"] in snap["positions"]]
            if state.get("resume_buy_state") is not None:
                if original_sell_stage:
                    self._persist_original_sell_execution(self._scoped_legacy_setting("best_same_day_catchup", {}), state["resume_buy_state"], now, snap, "BUY", {})
                else:
                    self.engine._set("best_execution", state["resume_buy_state"])
            state = self._partial_execution(now, "BUY", snap, deferred_sells=deferred)
        if not state["manifest"]:
            automatic = self._automatic_completion(now)
            unresolved = [row for row in state["skipped"] if not row.get("already_attempted") and not (
                automatic is not None and row.get("cash_limited")
                and row["code"] in state.get("target_quantities", {})
                and snap["positions"].get(row["code"], {}).get("qty", 0) >= state["target_quantities"][row["code"]])]
            if not unresolved:
                state.update(phase="DONE", completion_status="PARTIALLY_EXECUTED" if state["skipped"] else "EXECUTED")
                if reset:
                    reset.update(stage="COMPLETED", completed_at=now.isoformat(), completion_status=state["completion_status"])
                    with self.engine.db:
                        for key, value in (("best_execution", state), ("best_full_liquidation_reset", reset)):
                            self.engine.db.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))
                elif original_sell_stage:
                    self._persist_original_sell_execution(self._scoped_legacy_setting("best_same_day_catchup", {}), state, now, snap, "BUY", {})
                else:
                    self.engine._set("best_execution", state)
                self.status = state["completion_status"]
                self.reason = "本信号目标已处理；成交以券商真实对账为准"
            else:
                actual = any(row.get("fill_qty", 0) > 0 for row in self._current_session_orders()
                             if timestamp(row["created_at"]) >= timestamp(self.metadata["next_open_utc"]))
                self.status = ("RETRY_COOLDOWN" if any(row.get("retry_after_utc") for row in unresolved)
                               else "PARTIALLY_EXECUTED" if actual else "WAITING_QUOTES")
                self.reason = "; ".join(row["code"] + ": " + row["reason"] for row in unresolved)
            return
        if not self._source_send_ready(self._now()):
            return
        result = self.engine.step(respect_cancel=True, allow_partial_quotes=True,
                                  broker_order_type="MARKET")
        skipped = result.get("skipped", [])
        if skipped:
            state["skipped"].extend(skipped)
            if original_sell_stage:
                self._persist_original_sell_execution(self._scoped_legacy_setting("best_same_day_catchup", {}), state, now, snap, phase, {})
            else:
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
        if (state.get("phase") not in {"SELL", "BUY"} or manifest.get("strategy_id") != self.strategy_id
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
        if not self._source_send_ready(self._now()):
            return
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

    def _reuse_closed_completed_prepare(self, saved, now):
        """Reuse only the existing bounded preparation proof after all send windows closed."""
        execution = self.engine._get("best_execution",{})
        if (not self._closed_current_signal or self._source_validation_pending or self.engine._pending()
                or execution.get("signal_date")!=saved.get("metadata",{}).get("signal_date")
                or execution.get("phase")!="DONE" or execution.get("completion_status")!="EXECUTED"
                or self.plan!=saved.get("plan") or self.last_error
                or self.metadata.get("source_refs")!=saved.get("metadata",{}).get("source_refs")
                or self.metadata.get("status") not in {"READY","OPEN_WINDOW","MISSED_OPEN"} or self.metadata.get("data_gaps")
                or any(self.metadata.get(key)!=saved.get("metadata",{}).get(key) for key in ("signal_date","execution_date","next_open_utc","signal_close_utc"))
                or now.astimezone(ZoneInfo("America/New_York")).date().isoformat()!=self.metadata.get("execution_date")
                or not 0 <= time.monotonic()-self.prepared_at < 60):
            return False
        closing = self.metadata.get("next_close_utc")
        if closing is None:
            return False
        closing = timestamp(closing)
        if (closing<=now or closing.astimezone(ZoneInfo("America/New_York")).date().isoformat()!=self.metadata["execution_date"]):
            return False
        anchor = saved.get("metadata",{}).get("next_close_utc")
        manual = self._manual_completion_record(saved.get("plan"),saved.get("metadata"))
        if manual is not None:
            if timestamp(manual["session_close_utc"])!=closing:
                return False
            anchor = anchor or manual["session_close_utc"]
        if anchor is None or timestamp(anchor)!=closing:
            return False
        checked = self.metadata.get("now_utc")
        if checked is not None and not 0 <= (now-timestamp(checked)).total_seconds() < 60:
            return False
        opening = self.metadata.get("next_expected_open_utc")
        if opening is not None and timestamp(opening)<=now:
            return False
        refresh = self.metadata.get("next_refresh_utc")
        if refresh is not None and timestamp(refresh)<=now:
            # A past gate is handled only by a later successful owner check; no
            # future refresh date is fabricated. The canonical close remains a hard edge.
            if checked is None or timestamp(checked)<timestamp(refresh):
                return False
        return True

    def tick(self, now=None):
        owner = getattr(self, "_maintenance_owner", None)
        if owner is not None and owner._maintenance_active():
            return self.state()
        with self.lock:
            self._pending_repair_guard()
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
                    if not self._source_validation_pending:
                        self._maybe_reprice_pending(now)
                    self.status = "PENDING_RECONCILE"
                    self.reason = "已发送模拟委托，等待券商成交状态"
                    return
                self._require_running()
                snap = self.engine.broker.snapshot([], include_quotes=False)
                self._accept_snapshot(snap)
            self._complete_target_conversion(now)
            if self._source_validation_pending and time.monotonic() < self._source_retry_at:
                self.status, self.reason = "WAITING_SOURCE", "原输入验证暂忙；已暂停新委托，等待短暂重试"
                return
            saved = self.engine._get("best_plan", None)
            if (saved and saved.get("plan", {}).get("execution_mode") == "REBALANCE_EXISTING_POSITIONS"
                    and self._closed_execution(saved, now)):
                if not self._reuse_closed_completed_prepare(saved,now):
                    self._prepare(now)
                if self._closed_current_signal:
                    finished = self.engine._get("best_execution", {})
                    self.status = finished.get("completion_status", "EXECUTED") if finished.get("phase") == "DONE" else "PARTIALLY_EXECUTED"
                    missing = sorted({row["code"] for row in finished.get("skipped", [])} | {row["code"] for row in finished.get("deferred_sells", [])})
                    self.reason = "本期普通与补单窗口均已结束；保留冻结计划和真实成交，不补发" + ("；保留缺口：" + ", ".join(missing) if missing else "")
                    if self.last_error == "PUBLISHED_TARGET_CURRENT_SOURCE_BINDING_CHANGED":
                        self.last_error = ""
                        self.engine._set("best_last_error", "")
                    return
            new_closed_session = (self._closed_current_signal and self.metadata.get("execution_date")
                != now.astimezone(ZoneInfo("America/New_York")).date().isoformat())
            if self._source_validation_pending or new_closed_session or time.monotonic() - self.prepared_at > 60:
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
            self.engine.switch(self.strategy_id)
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
            if not self._source_send_ready(self._now()):
                return
            self.engine.step(respect_cancel=True)
            self.status = "PENDING_RECONCILE"
            self.reason = "已按策略差额提交一笔模拟委托，先对账再继续"

    @staticmethod
    def _skipped_source(execution):
        """Expose only dates proved by the skipped batch, never today's plan."""
        if not isinstance(execution, dict):
            return None
        signal = execution.get("signal_date")
        try:
            if not isinstance(signal, str) or datetime.strptime(signal, "%Y-%m-%d").date().isoformat() != signal:
                return None
            day = execution.get("execution_date")
            source = execution.get("manifest", {}).get("source") if isinstance(execution.get("manifest"), dict) else None
            if source is not None:
                origin = json.loads(source)
                if (not isinstance(origin, dict) or origin.get("kind") != "AUTHORIZED_MOOMOO_SIMULATE_EXECUTION_PLAN"
                        or origin.get("signal_date") != signal):
                    return None
                opening = timestamp(origin["next_open_utc"]).astimezone(ZoneInfo("America/New_York"))
                derived = opening.date().isoformat()
                if day is not None and day != derived:
                    return None
                day = derived
                if origin.get("execution_time_utc") and timestamp(origin["execution_time_utc"]).astimezone(
                        ZoneInfo("America/New_York")).date().isoformat() != day:
                    return None
            if (not isinstance(day, str) or datetime.strptime(day, "%Y-%m-%d").date().isoformat() != day
                    or day <= signal):
                return None
            return {"signal_date": signal, "execution_date": day}
        except (KeyError, TypeError, ValueError):
            return None

    def state(self):
        with self.lock:
            e = (self.engine.order_snapshot(account_id=self.engine._get("best_account",None))
                if self.engine.db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_epoch'").fetchone() else self.engine.order_snapshot())
            execution = self.engine._get("best_execution", {})
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
            execution_end = self._display_execution_end() if execution_at and self.plan else None
            if execution_end and self._now() < execution_end and self.status != "EXECUTED":
                expected_at = execution_at
            reset_state = {key: deepcopy(value) for key, value in self._scoped_legacy_setting("best_full_liquidation_reset", {}).items()
                if key in {"reset_id", "signal_date", "execution_date", "policy_id", "stage", "prepared_at",
                           "post_liquidation_baseline", "completed_at", "completion_status"}}
            baseline = reset_state.get("post_liquidation_baseline")
            if isinstance(baseline, dict):
                identity = baseline.get("account_id")
                baseline["account_id"] = "****" + identity[-4:] if isinstance(identity, str) else None
            provider = self.engine.automatic_completion_policy_provider
            saved_rule = provider() if callable(provider) else None
            if isinstance(saved_rule, dict) and self.strategy_id not in saved_rule.get("active_strategy_ids", []):
                saved_rule = None
            rule_summary = ({key: value for key, value in saved_rule.items() if key in {
                "schema_version", "execution_delay_minutes", "enabled", "policy_id", "effective_execution_date", "evaluation_end_exclusive",
                "priority_window_seconds", "close_buffer_seconds", "normal_spread_bps",
                "max_single_tick_spread_bps"}} if isinstance(saved_rule, dict) else None)
            standing_for_plan = bool(rule_summary and rule_summary.get("enabled")
                and rule_summary.get("effective_execution_date", "") <= self.metadata.get("execution_date", "")
                < rule_summary.get("evaluation_end_exclusive", ""))
            waiting_account = bool(rule_summary and rule_summary.get("enabled") and (
                self.engine.broker is None or self.engine.mode != "moomoo_simulate"))
            binding = deepcopy(self.engine._get("best_strategy_binding", None))
            if binding:
                binding.pop("preserved_settings", None)
                binding["account_id"] = "****" + str(binding["account_id"])[-4:]
            return dict(strategy_id=self.strategy_id, name=APPLIED_STRATEGY_NAMES[self.strategy_id], environment="SIMULATE",
                native_reset_epoch=self._native_reset_summary(),
                native_first_execution=(self._native_first_ack(native_first,self._now(),idempotent=True) if self.plan is not None and (native_first:=self._native_first_record()) is not None else None),
                account_state_origin=deepcopy(self.metadata.get("account_state_origin")),
                strategy_binding=binding, strategy_binding_precondition_sha256=self._strategy_binding_precondition(),
                published_target_alignment_precondition_sha256=self._target_alignment_precondition(),
                published_target_manual_completion=self._manual_completion_summary(),
                next_ordinary_execution_clock=deepcopy(self.engine._get("best_next_ordinary_execution_clock", None)),
                ordinary_execution_time_utc=execution_at.isoformat() if execution_at else None,
                ordinary_execution_deadline_utc=(execution_at+timedelta(seconds=self.execution_window_seconds)).isoformat() if execution_at else None,
                published_target_conversion={key:("****"+str(value)[-4:] if key=="account_id" else value)
                    for key,value in (self.engine._get("best_published_target_conversion",None) or {}).items()},
                published_target_alignment={key:("****"+str(value)[-4:] if key=="account_id" else value)
                    for key,value in (self.engine._get("best_published_target_alignment",None) or {}).items()
                    if key not in {"preserved_settings","positions_at_alignment","unused_cash"}},
                automatic_completion_policy=rule_summary,
                automatic_completion_deadline_status=("WAITING_ORIGINAL_ACCOUNT_RECONCILE" if waiting_account
                    else "CHECKED_WITH_ORIGINAL_ACCOUNT" if rule_summary and rule_summary.get("enabled") else None),
                running=not self.stop_event.is_set(), manual_data_updates=self.manual_data_updates, status=self.status, reason=self.reason,
                last_error=self.last_error, budget=self.budget, account_id=("****" + account_id[-4:]) if account_id != "paper" else None,
                cash=cash, equity=equity, positions=self.snapshot.get("positions", {}), orders=orders,
                order_count=len(orders), next_open_utc=self.metadata.get("next_open_utc"),
                next_expected_open_utc=self.metadata.get("next_expected_open_utc"), plan=self.plan,
                execution_delay_minutes=self.execution_delay_minutes, execution_window_seconds=self.execution_window_seconds,
                execution_deadline_utc=execution_end.isoformat() if execution_end else None,
                buy_order_type="MARKET" if self.allow_partial_quotes else "NORMAL",
                sell_order_type="MARKET" if self.allow_partial_quotes else "NORMAL",
                market_buy_cash_buffer=MARKET_BUY_CASH_BUFFER if self.allow_partial_quotes else None,
                reprice_policy=dict(interval_seconds=REPRICE_INTERVAL_SECONDS,
                                    max_attempts_per_order=MAX_REPRICES_PER_ORDER,
                                    terminal_retry_cooldown_seconds=TERMINAL_RETRY_COOLDOWN_SECONDS,
                                    max_terminal_retries_per_code=None if standing_for_plan else MAX_TERMINAL_RETRIES_PER_CODE,
                                    terminal_retry_policy="UNTIL_SESSION_CUTOFF" if standing_for_plan else "FIXED_RETRY_CAP",
                                    daily_order_limit=self.engine.limits["max_orders_per_day"],
                                    mode="SAME_BROKER_ORDER_ID", enabled=self.allow_partial_quotes),
                allow_partial_quotes=self.allow_partial_quotes, subscription_prewarm=self.prewarm_state,
                skipped=execution.get("skipped", []), skipped_source=self._skipped_source(execution),
                execution_time_utc=execution_at.isoformat() if execution_at else None,
                next_expected_execution_utc=expected_at.isoformat() if expected_at else None,
                full_liquidation_reset=reset_state,
                same_day_catchup={key: value for key, value in (self._scoped_legacy_setting("best_same_day_catchup", {}) or {}).items()
                    if key in {"signal_date", "execution_date", "authorized_at_utc", "deadline_utc", "reason", "include_deferred_sells"}},
                live_enabled=False)

    def close(self):
        self.stop()
        if self.worker and self.worker is not threading.current_thread():
            self.worker.join(timeout=10)
        self.engine.close()
