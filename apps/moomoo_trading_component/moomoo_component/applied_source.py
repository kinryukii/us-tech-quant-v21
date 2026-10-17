"""Frozen USTQ inputs for explicitly authorised paper accounts.

The public facade has no SDK dependencies. Its fixed-action worker runs in the
canonical Python environment, reads existing data, and never fits a model. Only
``refresh`` invokes the existing, globally locked recommendation updater.
Upstream ``broker_action_allowed=False`` remains unchanged; these are local
paper weight plans, not broker instructions or share quantities.
"""
from __future__ import annotations

from contextlib import redirect_stdout, closing
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import gc
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sqlite3
import sys
import tempfile
import threading
from zoneinfo import ZoneInfo


from .strategy import ACTIVE_PAPER_STRATEGY_IDS, LEGACY_PAPER_STRATEGY_IDS
from scripts.research.a2.inference.consensus_paper import PAPER_CURRENT_IDS

ACTIVE_STRATEGY_IDS = ACTIVE_PAPER_STRATEGY_IDS
LEGACY_STRATEGY_IDS = LEGACY_PAPER_STRATEGY_IDS
STRATEGY_IDS = tuple(dict.fromkeys(ACTIVE_STRATEGY_IDS + LEGACY_STRATEGY_IDS + PAPER_CURRENT_IDS))
HGB_RESET_STRATEGY_IDS = ("HGB_DIAG_5", "HGB_FACTOR_5")
OPEN_WINDOW_SECONDS = 60
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:\.[A-Z])?")
_HASH = re.compile(r"[0-9a-f]{64}")
_PROVENANCE = "EXPLICIT_LOCAL_PAPER_ADAPTER_FROZEN_USTQ"
_WORKER_LOCK = threading.Lock()
_WORKER_QUARANTINE_REASON = None
_WORKER_LOCK_TIMEOUT_SECONDS = 1.0
_WORKER_PROTOCOL_MAX_BYTES = 1024 * 1024
_REFRESH_WORKER_TIMEOUT_SECONDS = 3600


class DailySourceError(ValueError):
    def __init__(self, reason, *, data_gaps=None, source_refs=None):
        super().__init__(reason)
        self.reason = str(reason)
        self.data_gaps = data_gaps or [{"reason": self.reason}]
        self.source_refs = source_refs or {}



class _OwnedCleanupUnverified(DailySourceError):
    """An original runner returned without proof that its owned Windows tree ended."""
    def __init__(self, operation):
        self.operation = operation
        super().__init__("EXECUTION_CHART_CLEANUP_UNVERIFIED:" + operation)



def _worker_quarantine_reason():
    return _WORKER_QUARANTINE_REASON


def _quarantine_owned_worker(operation):
    # Publish before leaving any disposable log context: filesystem cleanup may
    # itself fail while the unknown child still holds a file. Same resource owner,
    # same lock; there is no automatic unquarantine or second lease implementation.
    global _WORKER_QUARANTINE_REASON
    if _WORKER_QUARANTINE_REASON is None:
        _WORKER_QUARANTINE_REASON = "EXECUTION_CHART_CLEANUP_UNVERIFIED:" + operation
    _WORKER_LOCK.acquire(blocking=False)  # Otherwise its current holder retains it on exit.
    return _WORKER_QUARANTINE_REASON



def _release_worker_lock_if_verified():
    if _worker_quarantine_reason() is None:
        _WORKER_LOCK.release()
        # Metadata can publish quarantine while a different holder is finishing.
        # The sticky guard rejects every new admission during this race; retain
        # this same lock again if it became free before that publication was seen.
        if _worker_quarantine_reason():
            _WORKER_LOCK.acquire(blocking=False)

def _require_worker_available():
    reason = _worker_quarantine_reason()
    if reason:
        raise _OwnedCleanupUnverified(reason.split(":",1)[1])

def _owned_cleanup_failure(result):
    # Only these exact original run_provider error/lifecycle signals prove that
    # cleanup itself failed. Ordinary module errors/timeouts are not equivalent.
    if result.get("lifecycle") == "WINDOWS_ATOMIC_JOB_KILL_ON_CLOSE":
        error = result.get("error", "")
        for operation in ("CLOSE_OWNED_JOB", "OWNED_PROCESS_TERMINATION"):
            if isinstance(error,str) and error.startswith("OSError:" + operation + ":"):
                return operation
    return None

def _utc(value=None):
    stamp = datetime.now(timezone.utc) if value is None else value
    if isinstance(stamp, str):
        stamp = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    if not isinstance(stamp, datetime) or stamp.tzinfo is None or stamp.utcoffset() is None:
        raise DailySourceError("ASOF_TIMEZONE_REQUIRED")
    return stamp.astimezone(timezone.utc)


def _iso(value):
    return _utc(value).isoformat().replace("+00:00", "Z")


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DailySourceError("ISO_SIGNAL_DATE_REQUIRED")
    date.fromisoformat(value)
    return value


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise DailySourceError("FINITE_NUMBER_REQUIRED")
    if value < 0 or (positive and value == 0):
        raise DailySourceError("NONNEGATIVE_NUMBER_REQUIRED")
    return float(value)


def _ticker(value):
    if not isinstance(value, str) or not _TICKER.fullmatch(value):
        raise DailySourceError("EXPLICIT_US_SYMBOL_ADAPTER_REQUIRED")
    return value


def _bytes(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _digest(path):
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _reference(path, expected=None):
    path = Path(path).resolve()
    actual = _digest(path)
    if expected is not None and (not _HASH.fullmatch(str(expected)) or actual != expected):
        raise DailySourceError("SOURCE_HASH_MISMATCH:" + path.name)
    return {"path": str(path), "sha256": actual}


def _json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise DailySourceError("SOURCE_JSON_OBJECT_REQUIRED")
    return payload


def _account_ids(accounts):
    if not isinstance(accounts, dict) or not accounts or set(accounts) - set(STRATEGY_IDS):
        raise DailySourceError("FIXED_PAPER_STRATEGY_IDS_REQUIRED")


def _state(state, signal_date, *, include_strategy_state=False):
    if not isinstance(state, dict) or state.get("valuation_basis") != "SIGNAL_CLOSE":
        raise DailySourceError("SIGNAL_CLOSE_STATE_REQUIRED")
    if state.get("signal_date") != signal_date:
        raise DailySourceError("ACCOUNT_STATE_DATE_MISMATCH")
    if any(key in state for key in ("execution_open", "next_open", "open_prices", "execution_date", "future_prices")):
        raise DailySourceError("FUTURE_ACCOUNT_INPUT_FORBIDDEN")
    if not isinstance(state.get("weights"), dict):
        raise DailySourceError("ACCOUNT_WEIGHTS_REQUIRED")
    weights = {_ticker(ticker): _number(weight) for ticker, weight in state["weights"].items()}
    weights = {ticker: weight for ticker, weight in weights.items() if weight > 0}
    cash = _number(state.get("cash_weight"))
    if abs(sum(weights.values()) + cash - 1) > 1e-8:
        raise DailySourceError("ACCOUNT_WEIGHTS_AND_CASH_MUST_SUM_TO_ONE")
    result = {"weights": weights, "cash_weight": cash, "signal_date": signal_date,
              "valuation_basis": "SIGNAL_CLOSE"}
    if not include_strategy_state:
        return result
    if "units" in state:
        if not isinstance(state["units"], dict):
            raise DailySourceError("ACCOUNT_UNITS_REQUIRED")
        result["units"] = {_ticker(t): _number(qty) for t, qty in state["units"].items() if qty}
        if set(result["units"]) != set(weights):
            raise DailySourceError("ACCOUNT_UNITS_WEIGHTS_IDENTITY_MISMATCH")
    if "security_ids" in state:
        if not isinstance(state["security_ids"], dict):
            raise DailySourceError("ACCOUNT_SECURITY_IDS_REQUIRED")
        result["security_ids"] = {ticker: str(state["security_ids"][ticker]) for ticker in weights if ticker in state["security_ids"]}
    if "previous_requested_gross" in state:
        gross = _number(state["previous_requested_gross"])
        if gross not in (0., .25, .5, .75, 1.):
            raise DailySourceError("R7_PREVIOUS_REQUESTED_GRID_REQUIRED")
        result["previous_requested_gross"] = gross
    return result


def _reset_request(value, *, now=None):
    """Validate a user-requested hypothetical cash start; never an account mark."""
    fields = {"reset_id", "requested_at", "strategy_ids", "signal_date",
              "expected_policy_id", "expected_package_sha256"}
    if not isinstance(value, dict) or set(value) != fields:
        raise DailySourceError("EXPLICIT_CASH_RESET_REQUEST_REQUIRED")
    reset_id = value["reset_id"]
    if not isinstance(reset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", reset_id):
        raise DailySourceError("SAFE_CASH_RESET_ID_REQUIRED")
    ids = value["strategy_ids"]
    if (not isinstance(ids, list) or not ids or any(not isinstance(sid, str) for sid in ids)
            or len(ids) != len(set(ids)) or set(ids) - set(HGB_RESET_STRATEGY_IDS)):
        raise DailySourceError("HGB_CASH_RESET_STRATEGY_IDS_REQUIRED")
    if value["expected_policy_id"] != "HGB_TOP20_RISK_R1":
        raise DailySourceError("DIRECT_HGB_CASH_RESET_POLICY_REQUIRED")
    expected = value["expected_package_sha256"]
    if not isinstance(expected, str) or not _HASH.fullmatch(expected):
        raise DailySourceError("CASH_RESET_PACKAGE_HASH_REQUIRED")
    requested_at = _utc(value["requested_at"])
    if requested_at > _utc(now):
        raise DailySourceError("FUTURE_CASH_RESET_REQUEST_FORBIDDEN")
    return {"reset_id": reset_id, "requested_at": _iso(requested_at),
            "strategy_ids": [sid for sid in HGB_RESET_STRATEGY_IDS if sid in ids],
            "signal_date": _day(value["signal_date"]),
            "expected_policy_id": value["expected_policy_id"],
            "expected_package_sha256": expected}



LEGACY_POLICY = "RAW_TOP20_FROZEN_LEGACY"


def _pending_repair_request(value, *, now=None):
    fields = {"repair_id", "prepared_at", "signal_date", "execution_date", "next_open_utc",
              "signal_close_utc", "expected_policy_id", "expected_package_sha256", "previous_archive"}
    if not isinstance(value, dict) or set(value) != fields:
        raise DailySourceError("PENDING_REPAIR_REQUEST_REQUIRED")
    if (not isinstance(value["repair_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", value["repair_id"])
            or value["expected_policy_id"] != LEGACY_POLICY
            or not isinstance(value["expected_package_sha256"], str)
            or not _HASH.fullmatch(value["expected_package_sha256"])):
        raise DailySourceError("PENDING_REPAIR_IDENTITY_REQUIRED")
    signal, execution = _day(value["signal_date"]), _day(value["execution_date"])
    clock, prepared = _utc(now), _utc(value["prepared_at"])
    close, opening = _utc(value["signal_close_utc"]), _utc(value["next_open_utc"])
    if not signal < execution or not close <= prepared <= clock < opening:
        raise DailySourceError("PENDING_REPAIR_BEFORE_OPEN_REQUIRED")
    previous = value["previous_archive"]
    if (not isinstance(previous, dict) or set(previous) != {"path", "sha256"}
            or not isinstance(previous["path"], str) or not Path(previous["path"]).is_absolute()
            or not _HASH.fullmatch(str(previous["sha256"]))):
        raise DailySourceError("PENDING_REPAIR_PREVIOUS_ARCHIVE_REQUIRED")
    return deepcopy(value)


def _pending_source_binding(result, metadata, package_sha256, now):
    """Check a normal pending signal without granting reset/catchup authority."""
    clock = _utc(now)
    if (result.get("status") != "READY" or result.get("ready") is not True or result.get("data_gaps")
            or result.get("model_fit_calls", 0) != 0
            or result.get("source_date") != metadata.get("signal_date")
            or any(result.get(key) != metadata.get(key) for key in
                   ("signal_date", "execution_date", "next_open_utc", "signal_close_utc"))
            or not _utc(metadata["signal_close_utc"]) <= clock < _utc(metadata["next_open_utc"])):
        raise DailySourceError("PENDING_REPAIR_CURRENT_SOURCE_INVALID")
    old, current = metadata.get("source_refs", {}), result.get("source_refs", {})
    if (not isinstance(current, dict) or current.get("selected/package.json", {}).get("sha256") != package_sha256
            or any(not old.get(key) or current.get(key) != old[key]
                   for key in ("frozen_calendar", "session_hours_rules"))):
        raise DailySourceError("PENDING_REPAIR_CURRENT_SOURCE_BINDING_CHANGED")
    return result


def _pending_plan_digest(value, kind):
    if kind == "cohort":
        value = {key: value.get(key) for key in ("plans", "plan_close_states", "plan_metadata")}
    return hashlib.sha256(_bytes(value)).hexdigest()


def _pending_repair_broker_ancestor_value(db, binding, marker):
    """Follow finite, exact audited binding predecessors of this same SIM."""
    row = db.execute("SELECT value FROM settings WHERE key='best_strategy_binding_history'").fetchone()
    if not row or len(row[0].encode("utf-8")) > _WORKER_PROTOCOL_MAX_BYTES:
        raise ValueError()
    history = json.loads(row[0])
    if not isinstance(history, dict) or not history:
        raise ValueError()
    # SQLite rowid gives actual commit order even when two requests share a
    # timestamp. The immediately preceding audited transition is the only
    # allowed predecessor; dictionary order or a convenient old plan is not.
    rows = db.execute("SELECT rowid,detail FROM audit WHERE event='SIM_STRATEGY_BOUND' ORDER BY rowid DESC LIMIT ?",
                      (len(history) + 1,)).fetchall()
    if not rows or json.loads(rows[0][1]) != binding:
        raise ValueError()
    account, budget = binding.get("account_id"), binding.get("budget")
    previous = None; seen = set()
    for _, raw_record in rows:
        record = json.loads(raw_record); request = record.get("request", {})
        identity = request.get("binding_id"); preserved = record.get("preserved_settings")
        if (not isinstance(identity, str) or identity in seen or history.get(identity) != record
                or not isinstance(preserved, dict) or hashlib.sha256(_bytes(preserved)).hexdigest() != record.get("preserved_settings_sha256")
                or record.get("account_id") != account or record.get("budget") != budget
                or json.loads(preserved.get("pending_plan_repair", "null")) != marker
                or request.get("expected_strategy_id") != record.get("previous_strategy_id")
                or request.get("target_strategy_id") != record.get("target_strategy_id")
                or record.get("target_strategy_id") not in ACTIVE_STRATEGY_IDS
                or record.get("previous_strategy_id") not in STRATEGY_IDS):
            raise ValueError()
        if previous is not None and (record["target_strategy_id"] != previous["previous_strategy_id"]
                or _utc(record["bound_at_utc"]) > _utc(previous["bound_at_utc"])):
            raise ValueError()
        seen.add(identity)
        raw = preserved.get("best_plan")
        if not isinstance(raw, str):
            raise ValueError()
        value = json.loads(raw)
        if _pending_repair_value_matches(value, "broker", marker):
            return value
        previous = record
    raise ValueError()


def _pending_repair_native_epoch_value(db, marker):
    """Verify a completed old repair through one audited native reset archive only.

    This is custody of the old commit, never admission to trade the new account.
    All archive values stay in this same database; no locator opens another root.
    """
    row = db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_epoch'").fetchone()
    if row is None:
        return None

    def raw_setting(key, limit):
        row = db.execute("SELECT value FROM settings WHERE key=? AND typeof(value)='text' "
            "AND length(CAST(value AS BLOB)) BETWEEN 1 AND ?", (key, limit)).fetchone()
        if row is None:
            raise ValueError()
        return row[0]

    raw = raw_setting("best_native_reset_epoch", _WORKER_PROTOCOL_MAX_BYTES)
    record = json.loads(raw)
    fields = {"schema", "reset_id", "request", "adopted_at_utc", "old_account_id", "new_account_id",
        "budget", "previous_strategy_id", "target_strategy_id", "archive_namespace", "archive_manifest",
        "archive_manifest_sha256", "ledger_prefix", "ledger_prefix_sha256", "native_snapshot",
        "native_snapshot_sha256", "eligible_accounts", "old_pending_repair_sha256",
        "initial_capital", "initial_capital_sha256"}
    if (not isinstance(record, dict) or set(record) != fields
            or record["schema"] != "NATIVE_SIM_RESET_ADOPTION_R1"
            or _bytes(record).decode("utf-8") != raw
            or not isinstance(record["reset_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", record["reset_id"])
            or not isinstance(record["request"], dict)
            or record["previous_strategy_id"] not in ACTIVE_STRATEGY_IDS
            or record["target_strategy_id"] not in ACTIVE_STRATEGY_IDS
            or any(not isinstance(record[k], str) or not re.fullmatch(r"[1-9][0-9]{0,19}", record[k])
                   for k in ("old_account_id", "new_account_id"))
            or record["old_account_id"] == record["new_account_id"]
            or type(record["budget"]) not in (int, float)
            or not 0 < record["budget"] <= sys.float_info.max):
        raise ValueError()
    namespace = "native_reset_archive/" + record["reset_id"] + "/"
    if (record["archive_namespace"] != namespace
            or raw_setting("native_reset_receipt/" + record["reset_id"], _WORKER_PROTOCOL_MAX_BYTES) != raw
            or db.execute("SELECT count(*) FROM audit WHERE event='NATIVE_SIM_RESET_ADOPTED' AND detail=?",
                          (raw,)).fetchone()[0] != 1):
        raise ValueError()
    binding = json.loads(raw_setting("best_strategy_binding", _WORKER_PROTOCOL_MAX_BYTES))
    if (not isinstance(binding, dict) or type(binding.get("schema_version")) is not int
            or binding != dict(schema_version=2, binding_type=record["schema"], native_reset_id=record["reset_id"],
            native_reset_record_sha256=hashlib.sha256(_bytes(record)).hexdigest(),
            account_id=record["new_account_id"], budget=record["budget"],
            previous_strategy_id=record["previous_strategy_id"], target_strategy_id=record["target_strategy_id"])):
        raise ValueError()
    capital = json.loads(raw_setting("best_capital", _WORKER_PROTOCOL_MAX_BYTES))
    if (json.loads(raw_setting("best_account", 256)) != record["new_account_id"]
            or json.loads(raw_setting("best_strategy_id", 256)) != record["target_strategy_id"]
            or not isinstance(capital, dict) or capital.get("account_id") != record["new_account_id"]
            or type(capital.get("budget")) not in (int, float) or capital.get("budget") != record["budget"]
            or capital != record["initial_capital"]):
        raise ValueError()
    for key in ("archive_manifest", "ledger_prefix", "native_snapshot", "initial_capital"):
        if (not isinstance(record[key], dict)
                or hashlib.sha256(_bytes(record[key])).hexdigest() != record[key + "_sha256"]):
            raise ValueError()
    snapshot = record["native_snapshot"]
    if (snapshot.get("funds_only") is not True or snapshot.get("positions") != {}
            or snapshot.get("open_orders") != [] or snapshot.get("quotes") != {}
            or not isinstance(snapshot.get("observed_at_utc"), str) or not isinstance(record["adopted_at_utc"], str)
            or _utc(snapshot["observed_at_utc"]) > _utc(record["adopted_at_utc"])
            or record["eligible_accounts"] != [dict(account_id=record["new_account_id"], market="US", environment="SIMULATE")]):
        raise ValueError()
    request = record["request"]
    if (set(request) != {"reset_id", "requested_at", "expected_old_account_id", "new_account_id",
                        "target_strategy_id", "expected_precondition_sha256", "budget"}
            or any(request[k] != record[k] for k in ("reset_id", "new_account_id", "target_strategy_id", "budget"))
            or type(request["budget"]) not in (int, float)
            or request["expected_old_account_id"] != record["old_account_id"]
            or not isinstance(request["expected_precondition_sha256"], str)
            or not _HASH.fullmatch(request["expected_precondition_sha256"])
            or not isinstance(request["requested_at"], str)
            or _utc(request["requested_at"]) > _utc(record["adopted_at_utc"])):
        raise ValueError()
    manifest = record["archive_manifest"]
    required = {"best_plan", "pending_plan_repair", "best_account", "best_capital", "best_strategy_id"}
    if not required.issubset(manifest) or not 1 <= len(manifest) <= 512:
        raise ValueError()
    total = 0
    for key, entry in manifest.items():
        if (not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.:-]{0,255}", key)
                or ".." in key or not isinstance(entry, dict) or set(entry) != {"archive_key", "sha256", "size_bytes"}
                or entry["archive_key"] != namespace + key or not isinstance(entry["sha256"], str)
                or not _HASH.fullmatch(entry["sha256"]) or type(entry["size_bytes"]) is not int
                or not 1 <= entry["size_bytes"] <= 16 * 1024 * 1024):
            raise ValueError()
        total += entry["size_bytes"]
    if (total > 64 * 1024 * 1024
            or db.execute("SELECT count(*) FROM settings WHERE substr(key,1,?)=?",
                          (len(namespace), namespace)).fetchone()[0] != len(manifest)):
        raise ValueError()
    legacy = {}
    for key, entry in manifest.items():
        value = raw_setting(entry["archive_key"], entry["size_bytes"])
        if (len(value.encode("utf-8")) != entry["size_bytes"]
                or hashlib.sha256(value.encode("utf-8")).hexdigest() != entry["sha256"]):
            raise ValueError()
        if key == "pending_plan_repair":
            if (entry["sha256"] != record["old_pending_repair_sha256"]
                    or db.execute("SELECT 1 FROM settings WHERE key='pending_plan_repair' AND value=?",
                                  (value,)).fetchone() is None):
                raise ValueError()
        elif key in required:
            legacy[key] = value
    old_capital = json.loads(legacy["best_capital"])
    if (json.loads(legacy["best_account"]) != record["old_account_id"]
            or json.loads(legacy["best_strategy_id"]) != record["previous_strategy_id"]
            or not isinstance(old_capital, dict) or old_capital.get("account_id") != record["old_account_id"]
            or type(old_capital.get("budget")) not in (int, float) or old_capital.get("budget") != record["budget"]):
        raise ValueError()
    value = json.loads(legacy["best_plan"])
    if (not _pending_repair_value_matches(value, "broker", marker)
            or _day(value["metadata"]["signal_date"]) > _utc(record["adopted_at_utc"]).astimezone(ZoneInfo("America/New_York")).date().isoformat()):
        raise ValueError()
    return value


def _pending_repair_archived_value(db, kind, current, marker):
    """Audited forward binding preserves the old paired repair; never skip it."""
    if kind == "cohort":
        if not isinstance(current, dict):
            raise ValueError()
        binding = current.get("strategy_membership_binding")
        if (not isinstance(binding, dict) or binding.get("prior_pending_plan_repair") != marker
                or binding.get("target_strategy_ids") != list(ACTIVE_STRATEGY_IDS)
                or current.get("active_strategy_ids") != binding["target_strategy_ids"]):
            raise ValueError()
        raw = binding.get("preserved_cohort_setting")
        if (not isinstance(raw, str) or hashlib.sha256(raw.encode("utf-8")).hexdigest()
                != binding.get("preserved_cohort_setting_sha256")):
            raise ValueError()
        rows = db.execute("SELECT detail FROM events WHERE event='STRATEGY_MEMBERSHIP_BOUND'")
    else:
        native_value = _pending_repair_native_epoch_value(db, marker)
        if native_value is not None:
            return native_value
        row = db.execute("SELECT value FROM settings WHERE key='best_strategy_binding'").fetchone()
        selected = db.execute("SELECT value FROM settings WHERE key='best_strategy_id'").fetchone()
        if not row or not selected:
            raise ValueError()
        binding = json.loads(row[0]); preserved = binding.get("preserved_settings")
        if (not isinstance(preserved, dict) or hashlib.sha256(_bytes(preserved)).hexdigest()
                != binding.get("preserved_settings_sha256") or binding.get("target_strategy_id") not in ACTIVE_STRATEGY_IDS
                or json.loads(selected[0]) != binding["target_strategy_id"]
                or json.loads(preserved.get("pending_plan_repair", "null")) != marker):
            raise ValueError()
        raw = preserved.get("best_plan")
        if not isinstance(raw, str):
            raise ValueError()
        rows = db.execute("SELECT detail FROM audit WHERE event='SIM_STRATEGY_BOUND'")
        if not any(json.loads(row[0]) == binding for row in rows):
            raise ValueError()
        value = json.loads(raw)
        if not _pending_repair_value_matches(value, "broker", marker):
            return _pending_repair_broker_ancestor_value(db, binding, marker)
        return value
    if not any(json.loads(row[0]) == binding for row in rows):
        raise ValueError()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError()
    return value


def _pending_repair_value_matches(value, kind, marker):
    if not isinstance(value, dict):
        return False
    signal = (value.get("plan_metadata", {}) if kind == "cohort" else value.get("metadata", {})).get("signal_date")
    if not isinstance(signal, str) or signal < marker["signal_date"]:
        return False
    if signal > marker["signal_date"] or _pending_plan_digest(value, kind) == marker["new_hashes"][kind]:
        return True
    # Preserve the one already-reviewed equivalent UTC spelling projection.
    metadata = value.get("plan_metadata", {})
    if (kind != "cohort" or metadata.get("execution_delay_minutes") != 0
            or metadata.get("execution_window_seconds") != 600 or metadata.get("allow_partial_quotes") is not True
            or not all(isinstance(metadata.get(key), str) and metadata[key] for key in ("execution_time_utc", "next_open_utc"))
            or _utc(metadata["execution_time_utc"]) != _utc(metadata["next_open_utc"])):
        return False
    projected = deepcopy(value); projected["plan_metadata"]["execution_time_utc"] = metadata["next_open_utc"]
    return _pending_plan_digest(projected, kind) == marker["new_hashes"][kind]


def _pending_repair_commit_guard(marker):
    """Both durable repair markers agree, including audited forward migrations."""
    if not marker:
        return
    try:
        if marker.get("phase") != "COMMITTED":
            raise ValueError()
        cohort_marker_raw = None
        for kind, file_key, setting in (("cohort", "cohort_db", "cohort"), ("broker", "broker_db", "best_plan")):
            path = Path(marker[file_key]).resolve()
            with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
                peer = db.execute("SELECT value FROM settings WHERE key='pending_plan_repair'").fetchone()
                row = db.execute("SELECT value FROM settings WHERE key=?", (setting,)).fetchone()
                if not peer or json.loads(peer[0]) != marker or not row:
                    raise ValueError()
                if kind == "cohort":
                    cohort_marker_raw = peer[0]
                elif (db.execute("SELECT 1 FROM settings WHERE key='best_native_reset_epoch'").fetchone()
                      and peer[0] != cohort_marker_raw):
                    raise ValueError()
                value = json.loads(row[0])
                if not _pending_repair_value_matches(value, kind, marker):
                    value = _pending_repair_archived_value(db, kind, value, marker)
                    if not _pending_repair_value_matches(value, kind, marker):
                        raise ValueError()
    except (OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
        raise DailySourceError("PENDING_REPAIR_UNFINISHED_OR_BINDING_CHANGED") from exc


def _assumed_states(request):
    return {sid: {"weights": {}, "cash_weight": 1.0,
                  "valuation_basis": "POST_LIQUIDATION_ASSUMPTION"}
            for sid in request["strategy_ids"]}


def _clock_status(now, signal, sessions, hours, source_date=None, source_ready=False):
    """Keep the signal's execution clock separate from the next future opening."""
    now, signal = _utc(now), _day(signal)
    if signal not in sessions or len(sessions) != len(set(sessions)) or sessions != sorted(sessions):
        raise DailySourceError("FROZEN_SESSION_IDENTITY_REQUIRED")
    index = sessions.index(signal)
    if index + 1 >= len(sessions):
        raise DailySourceError("EXECUTION_OUTSIDE_BOUND_CALENDAR")
    execution = sessions[index + 1]
    opening, closing = map(_utc, hours[execution])
    ny = ZoneInfo("America/New_York")
    conservative_close = datetime.combine(date.fromisoformat(signal), time(16), ny).astimezone(timezone.utc)
    if now < conservative_close:
        raise DailySourceError("SIGNAL_NOT_COMPLETED")
    expected = next((_utc(hours[day][0]) for day in sessions if _utc(hours[day][0]) > now), None)
    refresh = next((datetime.combine(date.fromisoformat(day), time(16), ny).astimezone(timezone.utc)
                    + timedelta(seconds=60) for day in sessions
                    if datetime.combine(date.fromisoformat(day), time(16), ny).astimezone(timezone.utc)
                    + timedelta(seconds=60) > now), None)
    missed = now >= opening + timedelta(seconds=OPEN_WINDOW_SECONDS)
    window = "MISSED_OPEN" if missed else "OPEN_WINDOW" if now >= opening else "WAITING_OPEN"
    ready = bool(source_ready and source_date == signal and not missed)
    status = window if ready and window == "OPEN_WINDOW" else "READY" if ready else (
        "MISSED_OPEN" if missed and source_ready and source_date == signal else "WAITING_SOURCE")
    return {"status": status, "window_status": window, "ready": ready,
            "execute_now": ready and window == "OPEN_WINDOW", "reason": "" if ready else status,
            "reason_code": "" if ready else status, "signal_date": signal,
            "latest_completed_signal_date": signal, "source_date": source_date,
            "execution_date": execution, "signal_close_utc": _iso(conservative_close),
            "next_open_utc": _iso(opening), "next_close_utc": _iso(closing),
            "next_expected_open_utc": _iso(expected) if expected else None,
            "upcoming_open_utc": _iso(expected) if expected else None,
            "next_refresh_utc": _iso(refresh) if refresh else None,
            "refresh_not_before_utc": _iso(conservative_close + timedelta(seconds=60)),
            "refresh_required": not source_ready or source_date != signal,
            "now_utc": _iso(now), "open_window_seconds": OPEN_WINDOW_SECONDS,
            "provenance": _PROVENANCE, "execution_mode": "LOCAL_PAPER",
            "broker_action_allowed": False, "model_fit_calls": 0, "data_gaps": []}


def _main_charts_metadata(repo_root, now, *, finite_ca_admission_ref=None):
    """Owned-worker metadata only; never infer, replay, decode ledgers or request providers."""
    from scripts.common.storage_paths import resolve
    from scripts.research.a2.evaluation import consensus_paper_performance as owner
    from scripts.research.a2.inference import consensus_paper as consumer
    paths, stamp = resolve(repo_root), _iso(_utc(now))
    driver = owner
    driver_arguments = {}
    context = {"driver_ref": _reference(owner.__file__)}
    try:
        if finite_ca_admission_ref is not None:
            from scripts.research.a2.evaluation import consensus_paper_ca_continuation as driver
            driver_arguments['finite_ca_admission_ref'] = deepcopy(finite_ca_admission_ref)
            context.update(driver_ref=_reference(driver.__file__), original_driver_ref=_reference(owner.__file__),
                finite_ca_admission_ref=deepcopy(finite_ca_admission_ref))
        proof = owner.completed_calendar(paths, stamp)
        context["target_session"] = proof["target_session"]
        pointer = paths.daily_root / "A2_consensus_paper/latest.json"
        if pointer.stat().st_size > 4096:
            raise DailySourceError("MAIN_CHART_SOURCE_POINTER_SIZE")
        publication = _json(pointer)
        context["publication_ref"] = _reference(publication["path"], publication["sha256"])
        current = driver.already_current(paths, proof, stamp, **driver_arguments)
        if current is not None:
            return dict(status="READY", context=context, end=current["end"], manifest_ref=current["manifest_ref"],
                models_loaded=0, ledger_values_decoded=0, broker_action_allowed=False)
        preflight = driver.run_qualified_main(paths, as_of=stamp, auto=True, execute=False, **driver_arguments)
        if preflight.get("status")!="METADATA_PREFLIGHT_READY_NOT_SOURCE_OR_REPLAY_QUALIFICATION":
            raise DailySourceError("MAIN_CHART_METADATA_PREFLIGHT_NOT_READY")
        context.update(target_session=preflight["end"], publication_ref=preflight["publication_ref"], capture_ref=preflight["capture_ref"])
        # Retry identity only: the original driver remains the source/CA qualifier.
        # Bind the exact accepted report coordinate used by its _current_quote_source;
        # no price, CA response, curve or ledger values are decoded here.
        head = owner.projected_metadata(preflight["publication_ref"], ("source_extension_ref",))
        extension = owner.projected_metadata(head["source_extension_ref"], ("current_day_proofs",))
        current = [row for row in extension["current_day_proofs"] if row["signal_date"] == preflight["end"]]
        if len(current) != 1:
            raise DailySourceError("MAIN_CHART_CURRENT_MAPPING_IDENTITY_REQUIRED")
        mapping = owner.verified(current[0]["mapping_ref"])
        context["daily_report_ref"] = owner.reference(mapping.parent.parent / "report.json")
        locator = owner.resolve_supplemental_ca_receipts(paths, target_session=preflight["end"],
            publication_ref=preflight["publication_ref"], capture_ref=preflight["capture_ref"],
            daily_report_ref=context["daily_report_ref"], as_of=stamp)
        if locator["locator_ref"] is not None:
            # Locator identity permits retry; only the original driver qualifies CA.
            context["supplemental_ca_locator_ref"] = locator["locator_ref"]
            context["ca_receipt_refs"] = deepcopy(locator["ca_receipt_refs"])
        consumer.resource_check()  # Original 1.5GiB/8GiB owner; no model work is admitted below it.
        request = dict(as_of=stamp, capture_ref=preflight["capture_ref"], context=deepcopy(context), **driver_arguments)
        if context.get("ca_receipt_refs"):
            request["ca_receipt_refs"] = deepcopy(context["ca_receipt_refs"])
        return dict(status="PREFLIGHT", context=context, end=preflight["end"], models_loaded=0,
            ledger_values_decoded=0, source_qualification="ORIGINAL_DRIVER_REQUIRED", broker_action_allowed=False,
            request=request)
    except (OSError,KeyError,TypeError,ValueError) as exc:
        reason = str(exc) if isinstance(exc,ValueError) else type(exc).__name__
        return dict(status="BLOCKED", context=context, reason=reason[:500], models_loaded=0,
            ledger_values_decoded=0, resource_blocked=reason=="CONSENSUS_RESOURCE_FLOOR", broker_action_allowed=False)



def _main_provider_result(result, log):
    summary = dict(result)
    if result.get("exit_code")!=0:
        try:
            with Path(log).open("rb") as stream:
                stream.seek(0,2);size=stream.tell();stream.seek(max(0,size-8192))
                lines=stream.read(8192).decode("utf-8",errors="replace").splitlines()
            for line in reversed(lines):
                try:value=json.loads(line)
                except (TypeError,ValueError):continue
                if isinstance(value,dict) and value.get("status")=="BLOCKED":
                    summary["reason"]=str(value.get("reason","MAIN_CHART_DRIVER_BLOCKED"))[:500]
                    break
        except OSError:pass
        summary.setdefault("reason","MAIN_CHART_DRIVER_FAILED")
        summary["resource_blocked"]=summary["reason"]=="CONSENSUS_RESOURCE_FLOOR"
    return summary


class _ExecutionChartsJob:
    """Poll adapter for the shared owned runner; owns no second spawn engine."""

    def __init__(self, paths, cache, *, legacy=True, main_request=None, main_reader=None):
        _require_worker_available()
        self._legacy, self._main_request, self._main_reader = legacy, deepcopy(main_request), main_reader
        self._cancel_event, self._done = threading.Event(), threading.Event()
        self._result = None
        self._quarantine_reason = None
        self._thread = threading.Thread(target=self._run, args=(paths, cache),
            daemon=True, name="execution-charts-owner")
        self._thread.start()

    def _run(self, paths, cache):
        acquired = False
        stages = {}
        try:
            from scripts.common.daily_support import run_provider
            _require_worker_available()
            # Reuse the canonical resource owner for the entire owned process tree.
            while not self._cancel_event.is_set():
                if _WORKER_LOCK.acquire(timeout=1):
                    acquired = True
                    _require_worker_available()
                    break
            if not acquired:
                raise InterruptedError("PROVIDER_CANCELLED")
            # Disposable adapter logs do not replace the original owner's receipts.
            with tempfile.TemporaryDirectory(prefix="chart_", dir=cache) as folder:
                stages = {}
                if getattr(self,"_legacy",True):
                    stages["legacy"] = run_provider(paths, "scripts.daily_recommendation", ["--execution-charts"],
                        Path(folder)/"legacy.log",timeout=_REFRESH_WORKER_TIMEOUT_SECONDS,cancel_event=self._cancel_event)
                    operation = _owned_cleanup_failure(stages["legacy"])
                    if operation:
                        self._quarantine_reason = _quarantine_owned_worker(operation)
                        raise _OwnedCleanupUnverified(operation)
                request = getattr(self,"_main_request",None)
                if request is not None and not self._cancel_event.is_set():
                    # Recheck the original metadata worker after waiting for the shared
                    # slot/legacy stage; an old accepted capture is never a current grant.
                    reader = getattr(self,"_main_reader",None)
                    if not callable(reader):
                        raise ValueError("MAIN_CHART_METADATA_READER_REQUIRED")
                    finite_ref = request.get('finite_ca_admission_ref')
                    current = reader(now=_utc(request["as_of"]), cancel_event=self._cancel_event, **(
                        {'finite_ca_admission_ref': deepcopy(finite_ref)} if finite_ref is not None else {}))
                    if (current.get("status") == "READY" and finite_ref is not None and
                            any(current.get('context', {}).get(key) != request['context'].get(key)
                                for key in ('driver_ref', 'original_driver_ref', 'publication_ref', 'finite_ca_admission_ref'))):
                        stages['main'] = dict(exit_code=2, reason='MAIN_CHART_FINITE_ADMISSION_IDENTITY_CHANGED', resource_blocked=False)
                    elif current.get("status") == "READY":
                        stages["main"] = dict(exit_code=0,action="ALREADY_CURRENT_PREFIX_VERIFIED")
                    elif (current.get("status") != "PREFLIGHT" or current.get("context") != request["context"]
                            or current.get("request",{}).get("capture_ref") != request["capture_ref"]
                            or current.get("request",{}).get("ca_receipt_refs",[]) != request.get("ca_receipt_refs",[])
                            or request.get("ca_receipt_refs",[]) != request["context"].get("ca_receipt_refs",[])
                            or current.get('request', {}).get('finite_ca_admission_ref') != finite_ref
                            or request['context'].get('finite_ca_admission_ref') != finite_ref):
                        reason = current.get("reason", "MAIN_CHART_METADATA_IDENTITY_CHANGED")
                        stages["main"] = dict(exit_code=2,reason=reason,resource_blocked=current.get("resource_blocked",False))
                    elif not self._cancel_event.is_set():
                        args=["--auto","--execute","--as-of",request["as_of"],"--capture-ref",json.dumps(request["capture_ref"],ensure_ascii=False)]
                        for ref in request.get("ca_receipt_refs",[]):
                            args.extend(["--ca-receipt-ref",json.dumps(ref,ensure_ascii=False)])
                        log=Path(folder)/"main.log"
                        provider = "scripts.research.a2.evaluation.consensus_paper_performance"
                        if finite_ref is not None:
                            provider = "scripts.research.a2.evaluation.consensus_paper_ca_continuation"
                            args.extend(['--finite-ca-admission-ref', json.dumps(finite_ref, ensure_ascii=False)])
                        result=run_provider(paths,provider,args,
                            log,timeout=_REFRESH_WORKER_TIMEOUT_SECONDS,cancel_event=self._cancel_event)
                        stages["main"] = result
                        operation = _owned_cleanup_failure(result)
                        if operation:
                            self._quarantine_reason = _quarantine_owned_worker(operation)
                            raise _OwnedCleanupUnverified(operation)
                        stages["main"]=_main_provider_result(result,log)
                code=next((value.get("exit_code",-1) for value in stages.values() if value.get("exit_code")!=0),0)
                self._result=dict(exit_code=code,stages=stages,cancelled=self._cancel_event.is_set())
        except _OwnedCleanupUnverified as exc:
            self._quarantine_reason = _quarantine_owned_worker(exc.operation)
            self._result = {"exit_code": -1, "status": "QUARANTINED", "error": exc.reason,
                "cleanup_verified": False, "stages": stages, "cancelled": self._cancel_event.is_set()}
        except BaseException as exc:
            reason = self.quarantine_reason()
            self._result = {"exit_code": -1, "error": reason or type(exc).__name__, "stages": stages,
                "cancelled": self._cancel_event.is_set()}
            if reason:
                self._quarantine_reason = reason
                self._result.update(status="QUARANTINED",cleanup_verified=False)
        finally:
            # run_provider and its job/group cleanup finish before releasing resources.
            if acquired:
                _release_worker_lock_if_verified()
            self._done.set()

    def quarantine_reason(self):
        return getattr(self,"_quarantine_reason",None) or _worker_quarantine_reason()

    def poll(self):
        if self.quarantine_reason():
            return None  # Thread exit is not owned-tree completion.
        return self._result.get("exit_code", -1) if self._done.is_set() else None

    def result(self):
        return deepcopy(self._result) if self._done.is_set() else None

    def cancel(self):
        self._cancel_event.set()
        self._thread.join(timeout=12)  # Shared cleanup has a 10-second bounded wait.
        if self._thread.is_alive():
            raise RuntimeError("EXECUTION_CHART_CLEANUP_PENDING")
        if self.quarantine_reason():
            raise RuntimeError(self.quarantine_reason())


class DailySource:
    """Dependency-light facade for the canonical, read-only source worker."""

    def __init__(self, repo_root="D:/us-tech-quant", *, runtime_root=None, python_exe=None):
        self.repo_root = Path(repo_root).resolve()
        self.runtime_root = Path(runtime_root).resolve() if runtime_root is not None else None
        from scripts.common.storage_paths import resolve
        paths = resolve(self.repo_root)
        self._read_only_roots = [paths.repo_root, paths.data_root]
        self.daily_root = paths.daily_root
        self.python_exe = Path(python_exe or paths.python_exe).resolve()

    def _call(self, action, *, _cancel_event=None, **values):
        _require_worker_available()
        request = {"action": action, "repo_root": str(self.repo_root), **values}
        # Status follows the same authoritative metadata/hash worker and loads no
        # fitted object (_bundle(full=False), candidate_source_refs). Keep it usable
        # while the single heavy owner runs; all other operations remain serialized.
        heavy = action not in {"status","main_charts_status"}
        if heavy and not _WORKER_LOCK.acquire(timeout=_WORKER_LOCK_TIMEOUT_SECONDS):
            raise DailySourceError("CANONICAL_SOURCE_WORKER_BUSY")
        cleanup_unverified = False
        try:
            _require_worker_available()
            from types import SimpleNamespace
            from scripts.common.daily_support import run_provider
            from scripts.common.storage_paths import resolve, assert_safe_output_path
            paths = resolve(self.repo_root)
            cache = (paths.cache_root / "moomoo_trading_component/canonical_source").resolve()
            assert_safe_output_path(cache, kind="cache", paths=paths)
            payload = _bytes(request)
            if len(payload) > _WORKER_PROTOCOL_MAX_BYTES:
                raise DailySourceError("CANONICAL_SOURCE_REQUEST_TOO_LARGE")
            cache.mkdir(parents=True, exist_ok=True)
            # Only this call's disposable protocol files are removed. Canonical
            # provider logs and accepted source/plan receipts retain their owner.
            with tempfile.TemporaryDirectory(prefix="request_", dir=cache) as folder:
                request_path = Path(folder) / "request.json"
                log = Path(folder) / "response.log"
                request_path.write_bytes(payload)
                worker = run_provider(SimpleNamespace(repo_root=self.repo_root, python_exe=self.python_exe),
                    "apps.moomoo_trading_component.moomoo_component.applied_source", ["--worker"], log,
                    timeout=_REFRESH_WORKER_TIMEOUT_SECONDS if action == "refresh" else 300,
                    input_path=request_path, **({"cancel_event":_cancel_event} if _cancel_event is not None else {}))
                operation = _owned_cleanup_failure(worker)
                if operation:
                    cleanup_unverified = True
                    _quarantine_owned_worker(operation)
                    raise _OwnedCleanupUnverified(operation)
                if worker.get("exit_code") != 0:
                    reason = ("CANONICAL_SOURCE_WORKER_TIMEOUT" if str(worker.get("error", "")).startswith("TimeoutExpired:")
                              else "CANONICAL_SOURCE_WORKER_UNAVAILABLE")
                    raise DailySourceError(reason)
                with log.open("rb") as stream:
                    raw = stream.read(_WORKER_PROTOCOL_MAX_BYTES + 1)
                if len(raw) > _WORKER_PROTOCOL_MAX_BYTES:
                    raise DailySourceError("CANONICAL_SOURCE_RESPONSE_TOO_LARGE")
                response = json.loads(raw.decode("utf-8"))
                if not isinstance(response, dict) or type(response.get("ok")) is not bool:
                    raise DailySourceError("CANONICAL_SOURCE_RESPONSE_INVALID")
                if not response["ok"]:
                    raise DailySourceError(response.get("reason", "CANONICAL_SOURCE_WORKER_FAILED"),
                        data_gaps=response.get("data_gaps"), source_refs=response.get("source_refs"))
                if not isinstance(response.get("result"), dict):
                    raise DailySourceError("CANONICAL_SOURCE_RESPONSE_INVALID")
                return response["result"]
        except DailySourceError:
            raise
        except (OSError, ValueError, KeyError, TypeError) as exc:
            # A log/directory cleanup error cannot erase a prior owned-tree failure.
            _require_worker_available()
            # Never echo logs, environment variables or provider output.
            raise DailySourceError("CANONICAL_SOURCE_WORKER_UNAVAILABLE:" + type(exc).__name__) from exc
        finally:
            if heavy and not cleanup_unverified:
                _release_worker_lock_if_verified()

    def status(self, now=None):
        return self._call("status", now=_iso(_utc(now)) if now is not None else None)

    def load(self, states=None, now=None, *, reset_request=None, repair_request=None):
        if repair_request is not None and (reset_request is not None or states is None):
            raise DailySourceError("PENDING_REPAIR_NORMAL_ACCOUNTS_REQUIRED")
        repair = _pending_repair_request(repair_request, now=now) if repair_request is not None else None
        values = {}
        if reset_request is not None:
            if states is not None:
                raise DailySourceError("CASH_RESET_AND_ACCOUNT_STATE_MUTUALLY_EXCLUSIVE")
            values["reset_request"] = _reset_request(reset_request, now=now)
        else:
            _account_ids(states)
        result = self._call("load", states=states,
                            now=_iso(_utc(now)) if now is not None else None, **values)
        if result.get("plans") and self.runtime_root is not None:
            self._archive(result, states, repair_request=repair)
        return result

    def close_states(self, books, signal_date):
        _account_ids(books)
        return self._call("close_states", books=books, signal_date=_day(signal_date))

    def refresh(self):
        """Run the original updater once; it owns provider access and its OS lock."""
        return self._call("refresh")

    def main_execution_charts_status(self, now=None, *, cancel_event=None, finite_ca_admission_ref=None):
        return self._call("main_charts_status", now=_iso(_utc(now)), _cancel_event=cancel_event, **(
            {'finite_ca_admission_ref': deepcopy(finite_ca_admission_ref)} if finite_ca_admission_ref is not None else {}))

    def start_execution_charts(self, *, legacy=True, main_request=None):
        """Run the original fixed chart updater in the shared finite owned job."""
        _require_worker_available()
        from types import SimpleNamespace
        from scripts.common.storage_paths import resolve, assert_safe_output_path
        paths = resolve(self.repo_root)
        cache = (paths.cache_root / "moomoo_trading_component/execution_charts").resolve()
        assert_safe_output_path(cache, kind="cache", paths=paths)
        cache.mkdir(parents=True, exist_ok=True)
        return _ExecutionChartsJob(SimpleNamespace(repo_root=self.repo_root, python_exe=self.python_exe), cache,
            legacy=legacy,main_request=main_request,main_reader=self.main_execution_charts_status)

    def execution_charts_status(self, execution_date):
        """Read the daily owner's small same-date receipt, without worker locks."""
        from scripts.common.storage_paths import resolve
        from scripts.research.a2.portfolio.selected_hgb import active_policy
        day = _day(execution_date)
        paths = resolve(self.repo_root)
        _, source = active_policy(paths)
        source = Path(source).resolve()
        if not source.is_relative_to(paths.daily_root.resolve()):
            raise DailySourceError('EXECUTION_CHART_SOURCE_OUTSIDE_DAILY_OWNER')
        package_sha = _digest(source)
        current_source = _json(source)['source_refs']['current/report.json']
        if _digest(current_source['path']) != current_source['sha256']:
            raise DailySourceError('EXECUTION_CHART_SOURCE_REPORT_CHANGED')
        receipt = (paths.daily_root / "A2_today_recommendation/execution_charts" / day /
                   package_sha[:16] / "state.json")
        try:
            if not receipt.resolve().is_relative_to((paths.daily_root / 'A2_today_recommendation/execution_charts' / day / package_sha[:16]).resolve()):
                raise ValueError('EXECUTION_CHART_RECEIPT_OUTSIDE_OWNER')
            with receipt.open("rb") as stream:
                payload = stream.read(65537)
            if len(payload) > 65536:
                raise ValueError("EXECUTION_CHART_RECEIPT_TOO_LARGE")
            value = json.loads(payload.decode("utf-8-sig"))
            if (value.get('schema') != 'A2_EXECUTION_CHART_REFRESH_STATE_V1'
                    or value.get("execution_date") != day or value.get("package_sha256") != package_sha
                    or value.get('source_report') != current_source
                    or value.get("broker_action_allowed") is not False):
                raise ValueError("EXECUTION_CHART_RECEIPT_BINDING_CHANGED")
            return {key: deepcopy(value.get(key)) for key in
                    ("status", "signal_date", "execution_date", "package_sha256", "source_report", "completed_at",
                     "action", "failed_stages", "benchmark_reference")}
        except (OSError, ValueError, KeyError) as exc:
            return {"status": "UNAVAILABLE", "execution_date": day, "reason": type(exc).__name__}

    def _archive(self, result, states=None, *, repair_request=None):
        # Different accounts/brokers have separate runtime roots. Volatile clock
        # fields are intentionally excluded from the immutable daily payload.
        runtime_root = self.runtime_root.resolve()
        for sid, plan in result.get("plans", {}).items():
            policy = plan.get("policy_id")
            if policy is not None and sid != "RAW_A2":
                allowed = {"RAW_TOP20_FROZEN_LEGACY", "HGB_TOP20_RISK_R1"} if sid in HGB_RESET_STRATEGY_IDS else {sid} if sid in PAPER_CURRENT_IDS else set()
                if policy not in allowed:
                    raise DailySourceError("PAPER_ARCHIVE_POLICY_IDENTITY_REQUIRED")
        policies = {plan["policy_id"] for sid, plan in result.get("plans", {}).items()
                    if sid != "RAW_A2" and plan.get("policy_id") is not None}
        if any(not isinstance(policy, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", policy)
               for policy in policies):
            raise DailySourceError("PAPER_ARCHIVE_POLICY_IDENTITY_REQUIRED")
        # New policies retain the existing account but never replace a legacy
        # plan already archived for the same signal date.
        archive_policy = "MULTI_FROZEN_PAPER_V1" if len(policies) > 1 else next(iter(policies), None)
        archive_root = runtime_root / "policies" / archive_policy if archive_policy else runtime_root
        if len(policies) > 1:
            # Recovery asks only for still-missing books. Distinct requested
            # subsets have distinct immutable envelopes, while each book keeps
            # its accepted same-day plan in the existing cohort authority.
            scope = {sid: plan.get("policy_id") for sid, plan in sorted(result.get("plans", {}).items())}
            archive_root = archive_root / hashlib.sha256(_bytes(scope)).hexdigest()[:20]
        reset = result.get("reset_request")
        if reset is not None:
            reset = _reset_request(reset)
            if (states is not None or policies != {reset["expected_policy_id"]}
                    or set(result.get("plans", {})) != set(reset["strategy_ids"])
                    or result.get("source_date") != reset["signal_date"]
                    or result.get("assumed_states") != _assumed_states(reset)
                    or result.get("reset_request_sha256") != hashlib.sha256(_bytes(reset)).hexdigest()
                    or any(plan.get("reset_id") != reset["reset_id"]
                           or plan.get("account_basis") != "USER_REQUESTED_POST_LIQUIDATION_CASH_START"
                           or plan.get("valuation_basis") != "POST_LIQUIDATION_ASSUMPTION"
                           for plan in result.get("plans", {}).values())):
                raise DailySourceError("CASH_RESET_ARCHIVE_IDENTITY_REQUIRED")
            archive_root = archive_root / "resets" / reset["reset_id"]
        repair = None
        if repair_request is not None:
            repair = _pending_repair_request(repair_request, now=repair_request["prepared_at"])
            if reset is not None or states is None or policies - {LEGACY_POLICY}:
                raise DailySourceError("PENDING_REPAIR_LEGACY_NORMAL_ACCOUNTS_REQUIRED")
            previous_path = Path(repair["previous_archive"]["path"]).resolve()
            original_root = (runtime_root / repair["signal_date"]).resolve()
            if (previous_path.name != "plans.json" or not previous_path.is_relative_to(original_root)
                    or (previous_path != original_root / "plans.json"
                        and previous_path.parent.parent != original_root / "pending_repairs")):
                raise DailySourceError("PENDING_REPAIR_ARCHIVE_OWNER_MISMATCH")
            _reference(previous_path, repair["previous_archive"]["sha256"])
            previous = _json(previous_path)
            _pending_source_binding(result, {**previous, "signal_date": previous.get("source_date"),
                "signal_close_utc": repair["signal_close_utc"]}, repair["expected_package_sha256"], repair["prepared_at"])
            if (previous.get("source_date") != repair["signal_date"]
                    or previous.get("execution_date") != repair["execution_date"]
                    or previous.get("next_open_utc") != repair["next_open_utc"]
                    or set(previous.get("plans", {})) != set(result.get("plans", {}))
                    or previous.get("states") != {sid: _state(state, result["source_date"]) for sid, state in states.items()}
                    or previous.get("model_fit_calls", 0) != 0
                    or any(plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY
                           or plan.get("valuation_basis") != "SIGNAL_CLOSE" or plan.get("reset_id")
                           or plan.get("execution_mode") for plan in previous["plans"].values())
                    or any(plan.get("policy_id", LEGACY_POLICY) != LEGACY_POLICY
                           or plan.get("valuation_basis") != "SIGNAL_CLOSE" or plan.get("reset_id")
                           or plan.get("execution_mode") or plan.get("model_fit_calls", 0) != 0
                           for plan in result["plans"].values())
                    or not any(key.startswith("frozen/") for key in previous.get("source_hashes", {}))
                    or {key: value for key, value in previous.get("source_hashes", {}).items() if key.startswith("frozen/")}
                       != {key: value for key, value in result.get("source_hashes", {}).items() if key.startswith("frozen/")}):
                raise DailySourceError("PENDING_REPAIR_PREVIOUS_ACCOUNT_OR_FROZEN_INPUT_CHANGED")
            archive_root = runtime_root
        destination = (archive_root / _day(result["source_date"]) / "plans.json").resolve()
        if any(runtime_root == root or runtime_root.is_relative_to(root) for root in self._read_only_roots):
            raise DailySourceError("PAPER_ARCHIVE_MUST_BE_OUTSIDE_CANONICAL_REPO")
        if runtime_root == self.daily_root or not destination.is_relative_to(self.daily_root):
            raise DailySourceError("PAPER_ARCHIVE_REQUIRES_DAILY_ROOT")
        stable = {key: deepcopy(result.get(key)) for key in (
            "source_date", "execution_date", "next_open_utc", "next_close_utc", "plans",
            "scores", "source_refs", "source_hashes", "coverage_gaps", "provenance", "model_fit_calls")}
        if reset is None:
            stable["states"] = {sid: _state(state, result["source_date"]) for sid, state in states.items()}
        else:
            stable.update(reset_request=deepcopy(reset),
                          reset_request_sha256=result["reset_request_sha256"],
                          assumed_states=deepcopy(result["assumed_states"]))
        if repair is not None:
            stable["pending_repair_request"] = repair
        raw = _bytes(stable)
        if repair is not None:
            destination = (runtime_root / repair["signal_date"] / "pending_repairs"
                / (repair["repair_id"] + "_" + hashlib.sha256(raw).hexdigest()[:20]) / "plans.json").resolve()
        if not destination.is_relative_to(runtime_root):
            raise DailySourceError("PENDING_REPAIR_ARCHIVE_OWNER_MISMATCH")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            try:
                os.link(temporary, destination)  # Atomic create, never replace a daily archive.
            except FileExistsError:
                previous_raw = destination.read_bytes()
                if previous_raw != raw:
                    matched = _archive_resource_recheck(previous_raw, stable)
                    if matched is None:
                        raise DailySourceError("IMMUTABLE_PAPER_PLAN_CONFLICT", source_refs=result.get("source_refs"))
                    previous, current = matched
                    for sid in current:
                        result["plans"][sid]["resource_receipt"] = deepcopy(previous["plans"][sid]["resource_receipt"])
                    result["archive_resource_recheck"] = dict(schema="FROZEN_ARCHIVE_RESOURCE_RECHECK_V1",
                        source_date=result["source_date"], execution_date=result["execution_date"],
                        preserved_archive_sha256=hashlib.sha256(previous_raw).hexdigest(),
                        current_resource_receipts=current)
                    raw = previous_raw  # Return the original receipt/hash, never rewrite frozen bytes.
        finally:
            temporary.unlink()
        result["archive"] = {"path": str(destination), "sha256": hashlib.sha256(raw).hexdigest()}


def _archive_resource_recheck(previous_raw, stable):
    """Reuse an exact frozen payload except valid, process-local memory counts."""
    try:
        previous = json.loads(previous_raw)
        if _bytes(previous) != previous_raw:
            return None  # Noncanonical bytes never acquire an idempotency exception.
        projected = deepcopy(stable)
        if not isinstance(previous.get("plans"), dict) or not isinstance(projected.get("plans"), dict):
            return None
        current = {}
        numeric = {"working_set_bytes", "process_peak_working_set_bytes", "pagefile_bytes"}
        sample_keys = numeric | {"status", "peak_scope"}
        for sid, plan in projected["plans"].items():
            if sid not in PAPER_CURRENT_IDS:
                continue
            old_plan = previous["plans"].get(sid)
            if not isinstance(plan, dict) or not isinstance(old_plan, dict):
                return None
            new_receipt, old_receipt = plan.get("resource_receipt"), old_plan.get("resource_receipt")
            if not isinstance(new_receipt, dict) or not isinstance(old_receipt, dict):
                return None
            for key in ("memory_before", "memory_after_model_release"):
                new_sample, old_sample = new_receipt.get(key), old_receipt.get(key)
                for sample in (new_sample, old_sample):
                    if (not isinstance(sample, dict) or set(sample) != sample_keys
                            or sample["status"] != "MEASURED" or sample["peak_scope"] != "CURRENT_WORKER_PROCESS"
                            or any(type(sample[name]) is not int or not 0 <= sample[name] < 2**64 for name in numeric)
                            or sample["process_peak_working_set_bytes"] < sample["working_set_bytes"]):
                        return None
                for name in numeric:
                    new_sample[name] = old_sample[name]
            if plan["resource_receipt"] != stable["plans"][sid]["resource_receipt"]:
                current[sid] = deepcopy(stable["plans"][sid]["resource_receipt"])
        if not current or _bytes(projected) != previous_raw:
            return None  # All decisions, states, refs, clocks and other proofs remain exact.
        return previous, current
    except (TypeError, ValueError, AttributeError):
        return None


class _CanonicalSource:
    def __init__(self, repo_root):
        self.repo_root = Path(repo_root).resolve()
        sys.path.insert(0, str(self.repo_root))
        from scripts.common.storage_paths import resolve
        from scripts.daily_recommendation_inputs import load_frozen_binding
        self.paths = resolve(self.repo_root)
        self.binding = load_frozen_binding(self.repo_root)
        self.refs = {}

    def _calendar(self, now):
        from scripts.daily_recommendation_inputs import latest_completed_session
        import exchange_calendars as xc
        metadata = latest_completed_session(self.binding, now)
        sessions = metadata["sessions"]
        calendar = xc.get_calendar("XNYS", start=sessions[0], end=sessions[-1])
        if list(calendar.sessions.strftime("%Y-%m-%d")) != sessions:
            raise DailySourceError("SESSION_HOURS_DISAGREE_WITH_FROZEN_CALENDAR")
        hours = {day: (_iso(calendar.session_open(day).to_pydatetime()),
                       _iso(calendar.session_close(day).to_pydatetime())) for day in sessions}
        self.refs["frozen_calendar"] = deepcopy(self.binding["readiness_sources"]["trading_calendar"])
        from exchange_calendars import exchange_calendar_xnys
        self.refs["session_hours_rules"] = _reference(exchange_calendar_xnys.__file__)
        self.hours_metadata = {"provider": "exchange_calendars.XNYS", "version": xc.__version__,
                               "schedule_sha256": hashlib.sha256(_bytes(hours)).hexdigest(),
                               "sessions_equal_frozen": True,
                               "completion_policy": "FROZEN_NY_16_CONSERVATIVE"}
        self.close_hours = hours
        return metadata["target_date"], sessions, hours

    def _bundle(self, full=False):
        from apps.demo_console.adapters.selected_strategies_reader import load_package
        from scripts.research.a2.portfolio import selected_hgb as hgb
        latest = self.paths.daily_root / "A2_today_recommendation/latest.json"
        pointer_ref = _reference(latest)
        latest_report = _json(latest)
        report_path = Path(latest_report["report_path"]).resolve()
        if not report_path.is_relative_to((self.paths.daily_root / "A2_today_recommendation/runs").resolve()):
            raise DailySourceError("CURRENT_REPORT_OUTSIDE_DAILY_RUNS")
        self.refs["daily/report.json"] = _reference(report_path, pointer_ref["sha256"])
        report = _json(report_path)
        signal = _day(report.get("data_date"))
        self.source_date = signal
        if (report.get("status") != "READY" or report.get("model_id") != "A2_HGB"
                or report.get("model_sha256") != hgb.A2_MODEL_SHA256):
            raise DailySourceError("CURRENT_SOURCE_NOT_FROZEN_READY")
        selected_policy, configured_package = hgb.active_policy(self.paths)
        package_path = Path(os.environ.get("USTQ_SELECTED_HGB_PACKAGE") or configured_package)
        package = load_package(package_path)
        if package.get("policy_id", hgb.LEGACY_POLICY) != selected_policy:
            raise DailySourceError("SELECTED_PACKAGE_ACTIVE_POLICY_MISMATCH")
        self.refs["selected/package.json"] = _reference(package_path, package["package_sha256"])
        source_ref = package["source_refs"]["current/report.json"]
        self.refs["selected/current_report.json"] = _reference(source_ref["path"], source_ref["sha256"])
        feature_report = _json(source_ref["path"])
        def ranks(value):
            return sorted((row["rank"], row["ticker"], str(row["security_id"]), row["score"])
                          for row in value.get("ranked_rows", value.get("rows", [])) if row["rank"] <= 40)
        if feature_report.get("data_date") != signal or ranks(report) != ranks(feature_report):
            raise DailySourceError("SELECTED_PACKAGE_CURRENT_REPORT_MISMATCH")
        feature = feature_report.get("selected_hgb_features")
        if not isinstance(feature, dict) or feature.get("signal_date") != signal:
            raise DailySourceError("CURRENT_FROZEN_FEATURE_SNAPSHOT_MISSING")
        self.refs["current/features.parquet"] = _reference(feature["path"], feature["sha256"])
        shared = package.get("shared_scores", {})
        scores = shared.get("current", {})
        if (shared.get("model_sha256") != hgb.FROZEN_HASHES["models/hgb_2026092501.joblib"] or scores.get("status") != "READY"
                or scores.get("signal_date") != signal or len(scores.get("rows", [])) != 40):
            raise DailySourceError("CURRENT_SHARED_SCORE_BINDING_MISSING")
        source_feature = package["source_refs"].get("current/selected_hgb_features.parquet", {})
        if source_feature.get("sha256") != feature["sha256"]:
            raise DailySourceError("PACKAGE_FEATURE_HASH_MISMATCH")
        if _digest(latest) != pointer_ref["sha256"] or _digest(package_path) != package["package_sha256"]:
            raise DailySourceError("CURRENT_SOURCE_CHANGED_DURING_READ")
        frame = None
        if full:
            hgb.verify_frozen(package.get("source_root"))
            import pandas as pd
            import numpy as np
            frame, day, reason = hgb._current_day(self.paths, Path(source_ref["path"]), self.refs)
            if frame is None or day != signal or reason:
                raise DailySourceError(reason or "CURRENT_FEATURE_DATE_MISMATCH")
            frame, day = hgb._normalise_day(frame, {"pd": pd, "np": np})
            # Score identities must match the exact verified feature/ranking rows.
            expected = {(str(row.ticker), int(row.raw_rank), str(row.security_id), float(row.raw_score))
                        for row in frame.itertuples()}
            actual = {(row["ticker"], row["raw_rank"], str(row["security_id"]), row["raw_score"])
                      for row in scores["rows"]}
            if expected != actual:
                raise DailySourceError("CURRENT_SCORE_SECURITY_OR_RANKING_MISMATCH")
        return report, package, frame

    def status(self, now=None):
        now = _utc(now)
        signal, sessions, hours = self._calendar(now)
        source_ready, error = False, None
        self.source_date = None
        try:
            report, package, _ = self._bundle()
            close = datetime.combine(date.fromisoformat(self.source_date), time(16),
                                     ZoneInfo("America/New_York")).astimezone(timezone.utc)
            if (not isinstance(report.get("generated_at"), str) or not isinstance(package.get("generated_at"), str)
                    or not close <= _utc(report["generated_at"]) <= now or _utc(package["generated_at"]) > now):
                raise DailySourceError("SOURCE_GENERATED_CLOCK_MISMATCH")
            source_ready = True
        except (OSError, ValueError, KeyError) as exc:
            error = exc
        result = _clock_status(now, signal, sessions, hours, self.source_date, source_ready)
        result.update(source_refs=deepcopy(self.refs), session_hours=deepcopy(self.hours_metadata))
        if error is not None:
            result["data_gaps"] = [{"reason": str(error) if isinstance(error, DailySourceError)
                                     else "CURRENT_SOURCE_UNAVAILABLE:" + type(error).__name__}]
        elif self.source_date != signal:
            result["data_gaps"] = [{"reason": "LATEST_COMPLETED_SOURCE_REQUIRED",
                                    "required_date": signal, "available_date": self.source_date}]
        return self._candidate_status_refs(result, now)

    def _candidate_status_refs(self, result, now):
        """Verify each implemented candidate independently without fitted objects."""
        result["candidate_source_scope"] = "PAPER_CANDIDATE_REFS_V1"
        statuses = result.setdefault("strategy_status", {})
        from scripts.research.a2.inference import consensus_paper as owner
        try:
            document, publication = owner.load_publication(self.paths, result["signal_date"], _iso(_utc(now)))
        except Exception as exc:
            for sid in owner.PAPER_CURRENT_IDS:
                statuses[sid] = {"status": "BLOCKED", "reason": str(exc), "signal_date": result["signal_date"]}
            return result
        for sid in owner.PAPER_CURRENT_IDS:
            try:
                candidate, candidate_ref = ((document, publication) if sid in owner.NEW_IDS else
                    owner.load_publication(self.paths, result["signal_date"], _iso(_utc(now)), paper_current=True))
                refs = owner.candidate_source_refs(self.paths, sid, candidate, candidate_ref, as_of=_iso(_utc(now)))
                result["source_refs"].update({sid + "/" + key: value for key, value in refs.items()})
                statuses[sid] = {"status": "READY", "signal_date": result["signal_date"]}
            except Exception as exc:
                statuses[sid] = {"status": "BLOCKED", "reason": str(exc), "signal_date": result["signal_date"]}
        return result

    def _identities(self, report):
        import pandas as pd
        universe = report["universe"]
        path = Path(universe["report_path"]).parent / "mapped_members.parquet"
        self.refs["current/mapped_members.parquet"] = _reference(path, universe["universe_members_sha256"])
        frame = pd.read_parquet(path, columns=["ticker", "security_id"])
        identities = {}
        for row in frame.itertuples():
            ticker, security = str(row.ticker), str(row.security_id).strip()
            if not security or security in {"nan", "None"} or ticker in identities:
                raise DailySourceError("CURRENT_SECURITY_IDENTITY_AMBIGUOUS")
            identities[ticker] = security
        return identities

    def _closes(self, tickers, signal, identities):
        """Verified native raw USD closes; keep provider and qualification explicit."""
        from scripts.storage.storage_r2a import DataStore
        store, prices = DataStore(self.paths), {}
        qualified_lineage, lineage_ref, frozen_alpha_source = None, None, None
        for ticker in sorted(tickers):
            _ticker(ticker)
            if ticker not in identities:
                raise DailySourceError("HELD_SECURITY_IDENTITY_UNKNOWN:" + ticker)
            try:
                metadata = store.metadata("prices_daily", ticker, "raw")
                if metadata.get("adjustment") != "raw" or metadata.get("source") not in {"MOOMOO", "MOOMOO_OPEND"}:
                    raise DailySourceError("RAW_CLOSE_METADATA_BASIS_MISMATCH:" + ticker)
                ref = _reference(metadata["path"], metadata["source_sha256"])
                inputs = store.resolve_price_inputs(metadata, verify_raw=True)
                frame = store.daily(ticker, "raw", signal, signal, provider="moomoo")
                if len(frame) == 0:
                    # A genuine native-date gap may use the already qualified
                    # raw provider leaf. Integrity/identity/clock errors never
                    # fall through to this branch, and no PIT index is a mark.
                    from scripts import daily_recommendation_prices as original
                    if qualified_lineage is None:
                        report, _, _ = self._bundle()
                        if report.get("data_date") != signal:
                            raise DailySourceError("RAW_CLOSE_QUALIFICATION_DATE_MISMATCH")
                        lineage_path = Path(report["report_path"]).parent / "input_lineage.json"
                        lineage_bytes = lineage_path.read_bytes()
                        recorded = json.loads(lineage_bytes)
                        if (not isinstance(recorded, list)
                                or hashlib.sha256(json.dumps(recorded, sort_keys=True).encode()).hexdigest()
                                != report.get("input_manifest_sha256")
                                or len({entry["ticker"] for entry in recorded}) != len(recorded)):
                            raise DailySourceError("RAW_CLOSE_QUALIFICATION_LINEAGE_INVALID")
                        lineage_ref = _reference(lineage_path, hashlib.sha256(lineage_bytes).hexdigest())
                        qualified_lineage = {entry["ticker"]: entry for entry in recorded}
                    entry = qualified_lineage.get(ticker, {})
                    bridge = entry.get("alternate_bridge") or {}
                    if (entry.get("code") != "US." + ticker
                            or entry.get("source") != "MOOMOO_RAW_PLUS_QUALIFIED_MASSIVE_TAIL_PLUS_MOOMOO_REHAB"
                            or bridge.get("provider") != "MASSIVE_GROUPED"
                            or bridge.get("qualification") != "UNADJUSTED_RAW_WITH_FIVE_SESSION_MOOMOO_OVERLAP"
                            or bridge.get("overlap_sessions") != 5
                            or bridge.get("provider_symbol") != ticker or bridge.get("tail_end") != signal):
                        raise DailySourceError("QUALIFIED_RAW_CLOSE_BRIDGE_REQUIRED:" + ticker)
                    anchors = [item for item in entry.get("raw_sources", [])
                               if item.get("role") in {"CURRENT_CATALOG_RAW", "NATIVE_MOOMOO_ANCHOR"}]
                    if (len(anchors) != 1 or Path(anchors[0]["path"]).resolve() != Path(ref["path"])
                            or anchors[0]["sha256"] != ref["sha256"]):
                        raise DailySourceError("QUALIFIED_RAW_CLOSE_NATIVE_ANCHOR_CHANGED:" + ticker)
                    native_guards = []
                    if "adapter_sha256" in entry:
                        if (entry["adapter_sha256"] != original.ADAPTER_SHA
                                or anchors[0]["role"] != "CURRENT_CATALOG_RAW"):
                            raise DailySourceError("QUALIFIED_RAW_CLOSE_LEGACY_ADAPTER_REQUIRED:" + ticker)
                    else:
                        # The existing native-2026 adapter deliberately makes
                        # no original frozen-anchor equivalence claim. Accept
                        # only its complete, current membership-bound schema.
                        anchor = entry.get("anchor_proof") or {}
                        native_proof = {key: value for key, value in anchors[0].items() if key != "role"}
                        if (anchors[0]["role"] != "NATIVE_MOOMOO_ANCHOR"
                                or anchor.get("kind") != "NEW_13F_MEMBER_NATIVE_RAW_ANCHOR"
                                or anchor.get("scope") != "2026_INFERENCE_ONLY"
                                or anchor.get("old_frozen_equivalence_claimed") is not False
                                or anchor.get("native_source") != native_proof
                                or native_proof.get("provider") != metadata["source"]
                                or native_proof.get("provider_code") != "US." + ticker
                                or native_proof.get("adjustment") != "RAW"
                                or entry.get("security_id") != identities[ticker]
                                or entry.get("security_ids") != [identities[ticker]]
                                or entry.get("membership_validation") != "CALLER_VERIFIED_CURRENT_PIT_UNIVERSE"
                                or entry.get("universe_id") != report["universe"]["universe_id"]
                                or entry.get("universe_effective_date") != report["universe"]["effective_date"]
                                or entry.get("observed_target") != signal or entry.get("raw_end") != signal):
                            raise DailySourceError("QUALIFIED_RAW_CLOSE_NATIVE_SCHEMA_REQUIRED:" + ticker)
                        if frozen_alpha_source is None:
                            from scripts.daily_recommendation_inputs import load_frozen_binding
                            binding = load_frozen_binding(self.repo_root)
                            frozen_alpha_source = next(item for item in binding["components"]["ALPHA"]["artifacts"]
                                                       if item["artifact_id"] == "source")
                        feature_source = entry.get("feature_source") or {}
                        if (Path(feature_source["path"]).resolve() != Path(frozen_alpha_source["path"]).resolve()
                                or feature_source["sha256"] != frozen_alpha_source["sha256"]):
                            raise DailySourceError("QUALIFIED_RAW_CLOSE_NATIVE_FEATURE_SOURCE_MISMATCH:" + ticker)
                        native_guards = [_reference(feature_source["path"], feature_source["sha256"])]
                        for name in ("daily/report.json", "current/mapped_members.parquet"):
                            bound = self.refs[name]
                            native_guards.append(_reference(bound["path"], bound["sha256"]))
                    native_anchor = {**ref, "qualification_role": anchors[0]["role"],
                                     "source": metadata["source"], "inputs": inputs}
                    massive = store.metadata("prices_daily_massive", ticker, "raw")
                    if (Path(massive["path"]).resolve() != Path(bridge["normalized_path"]).resolve()
                            or massive["source_sha256"] != bridge["normalized_sha256"]):
                        raise DailySourceError("QUALIFIED_RAW_CLOSE_RECORD_CHANGED:" + ticker)
                    massive_ref = _reference(massive["path"], massive["source_sha256"])
                    raw, proof = original._massive_raw_window(massive, ticker, signal, signal, store)
                    if len(raw) != 1:
                        raise DailySourceError("EXACT_MASSIVE_RAW_CLOSE_REQUIRED:" + ticker)
                    row = raw.iloc[0].to_dict()
                    if (row.get("date") != signal or row.get("ticker") != ticker
                            or row.get("source") != "MASSIVE_GROUPED" or row.get("adjustment") != "raw"
                            or row.get("currency") != "USD" or row.get("provider_code") != ticker
                            or not isinstance(row.get("observed_at"), str)
                            or not _utc(self.close_hours[signal][1]) <= _utc(row["observed_at"]) <= _utc()):
                        raise DailySourceError("MASSIVE_RAW_CLOSE_IDENTITY_OR_CLOCK_MISMATCH:" + ticker)
                    prices["US." + ticker] = _number(float(row["close"]), positive=True)
                    later = store.metadata("prices_daily_massive", ticker, "raw")
                    if (_digest(massive["path"]) != massive_ref["sha256"]
                            or later["source_sha256"] != massive_ref["sha256"]
                            or Path(later["path"]).resolve() != Path(massive_ref["path"])
                            or _digest(lineage_ref["path"]) != lineage_ref["sha256"]):
                        raise DailySourceError("QUALIFIED_RAW_CLOSE_CHANGED_DURING_READ:" + ticker)
                    native_later = store.metadata("prices_daily", ticker, "raw")
                    if (_digest(metadata["path"]) != ref["sha256"]
                            or native_later["source_sha256"] != ref["sha256"]
                            or Path(native_later["path"]).resolve() != Path(ref["path"])):
                        raise DailySourceError("RAW_CLOSE_CHANGED_DURING_READ:" + ticker)
                    if any(_digest(bound["path"]) != bound["sha256"] for bound in native_guards):
                        raise DailySourceError("QUALIFIED_RAW_CLOSE_NATIVE_BINDING_CHANGED_DURING_READ:" + ticker)
                    self.refs["close/" + ticker] = {**massive_ref, "signal_date": signal,
                        "price_basis": "RAW", "currency": "USD", "source": "MASSIVE_GROUPED",
                        "currency_basis": "MASSIVE_US_GROUPED_MARKET_RAW_USD", "provider_code": ticker,
                        "security_id": identities[ticker], "row_source_id": row["source_id"],
                        "observed_at": row["observed_at"], "inputs": proof["raw_inputs"],
                        "qualification_lineage": lineage_ref, "native_anchor": native_anchor,
                        "native_qualification_refs": native_guards,
                        "qualification": bridge["qualification"]}
                    continue
                if len(frame) != 1:
                    raise DailySourceError("EXACT_RAW_CLOSE_REQUIRED:" + ticker)
                row = frame.iloc[0].to_dict()
                if (str(row["date"])[:10] != signal or row["ticker"] != ticker or row["adjustment"] != "raw"
                        or row["source"] not in {"MOOMOO", "MOOMOO_OPEND"}
                        or row["provider_code"] != "US." + ticker
                        or row.get("currency", "USD") != "USD"
                        or row["source_id"] not in {item["sha256"] for item in inputs}):
                    raise DailySourceError("RAW_USD_CLOSE_IDENTITY_OR_BASIS_MISMATCH:" + ticker)
                if (not isinstance(row.get("observed_at"), str)
                        or not _utc(self.close_hours[signal][1]) <= _utc(row["observed_at"]) <= _utc()):
                    raise DailySourceError("RAW_CLOSE_OBSERVATION_CLOCK_MISMATCH:" + ticker)
                prices["US." + ticker] = _number(float(row["close"]), positive=True)
                later = store.metadata("prices_daily", ticker, "raw")
                if (_digest(metadata["path"]) != ref["sha256"] or later["source_sha256"] != ref["sha256"]
                        or Path(later["path"]).resolve() != Path(ref["path"])):
                    raise DailySourceError("RAW_CLOSE_CHANGED_DURING_READ:" + ticker)
                self.refs["close/" + ticker] = {**ref, "signal_date": signal, "price_basis": "RAW",
                    "currency": "USD", "currency_basis": "MOOMOO_US_MARKET_PROVIDER_CODE",
                    "provider_code": "US." + ticker, "security_id": identities[ticker],
                    "row_source_id": row["source_id"], "observed_at": row["observed_at"], "inputs": inputs}
            except DailySourceError:
                raise
            except (OSError, KeyError, ValueError, TypeError) as exc:
                raise DailySourceError("HELD_RAW_CLOSE_UNAVAILABLE:" + ticker,
                                       data_gaps=[{"ticker": ticker, "date": signal,
                                                   "reason": type(exc).__name__}], source_refs=self.refs) from exc
        return prices

    def close_states(self, books, signal_date):
        _account_ids(books)
        signal = _day(signal_date)
        now = _utc()
        complete, sessions, hours = self._calendar(now)
        if signal not in sessions or signal > complete:
            raise DailySourceError("CLOSE_STATE_REQUIRES_COMPLETED_FROZEN_SESSION")
        parsed, held = {}, set()
        for sid, book in books.items():
            if not isinstance(book, dict) or not isinstance(book.get("positions"), dict):
                raise DailySourceError("PAPER_BOOK_CASH_AND_POSITIONS_REQUIRED")
            quantities = {}
            for code, quantity in book["positions"].items():
                if not isinstance(code, str) or not code.startswith("US."):
                    raise DailySourceError("EXPLICIT_US_SYMBOL_ADAPTER_REQUIRED")
                ticker = _ticker(code[3:])
                qty = _number(quantity)
                if qty:
                    quantities[ticker] = qty
                    held.add(ticker)
            parsed[sid] = (_number(book.get("cash")), quantities)
        identities, prices = {}, {}
        if held:
            report, _, _ = self._bundle()
            if report["data_date"] != signal:
                raise DailySourceError("HELD_CLOSE_SOURCE_DATE_MISMATCH")
            identities = self._identities(report)
            prices = self._closes(held, signal, identities)
        result = {}
        for sid, (cash, positions) in parsed.items():
            values = {ticker: qty * prices["US." + ticker] for ticker, qty in positions.items()}
            equity = _number(cash + sum(values.values()), positive=True)
            result[sid] = {"units": dict(positions), "weights": {ticker: value / equity for ticker, value in values.items()},
                "cash_weight": cash / equity, "signal_date": signal, "valuation_basis": "SIGNAL_CLOSE",
                "equity": equity, "prices": {"US." + ticker: prices["US." + ticker] for ticker in positions},
                "security_ids": {ticker: identities[ticker] for ticker in positions},
                "source_refs": deepcopy(self.refs), "close_asof_utc": _iso(hours[signal][1]),
                "price_basis": "RAW_USD_CLOSE", "provenance": _PROVENANCE}
        return result

    def load(self, states=None, now=None, *, reset_request=None):
        reset = None
        if reset_request is not None:
            if states is not None:
                raise DailySourceError("CASH_RESET_AND_ACCOUNT_STATE_MUTUALLY_EXCLUSIVE")
            reset = _reset_request(reset_request, now=now)
        else:
            _account_ids(states)
        result = self.status(now)
        result["plans"], result["scores"] = {}, None
        if reset is not None:
            result.update(reset_id=reset["reset_id"], requested_at=reset["requested_at"],
                          reset_request=deepcopy(reset),
                          reset_request_sha256=hashlib.sha256(_bytes(reset)).hexdigest(),
                          assumed_states=_assumed_states(reset))
        # A stale complete source may still be displayed, but only its exact
        # original date/state is accepted. It can never become executable.
        if result["source_date"] is None or result["data_gaps"]:
            return self._new_plans(result, states, now) if reset is None else result
        from scripts.research.a2.portfolio import selected_hgb as hgb
        report = package = frame = application = None
        try:
            if reset is not None and not result.get("ready"):
                raise DailySourceError("CASH_RESET_REQUIRES_READY_CURRENT_SOURCE")
            report, package, frame = self._bundle(full=True)
            signal = report["data_date"]
            if reset is None:
                accounts = {sid: _state(state, signal) for sid, state in states.items() if sid in LEGACY_STRATEGY_IDS}
            else:
                if (signal != reset["signal_date"] or result.get("source_date") != signal
                        or result.get("signal_date") != signal):
                    raise DailySourceError("CASH_RESET_SIGNAL_DATE_MISMATCH")
                if (package.get("policy_id") != reset["expected_policy_id"]
                        or package.get("package_sha256") != reset["expected_package_sha256"]
                        or self.refs.get("selected/package.json", {}).get("sha256")
                        != reset["expected_package_sha256"]):
                    raise DailySourceError("CASH_RESET_SOURCE_BINDING_MISMATCH")
                accounts = _assumed_states(reset)
            identities = self._identities(report)
            for row in report.get("ranked_rows", report.get("rows", [])):
                if row["rank"] <= 40 and identities.get(row["ticker"]) != str(row["security_id"]):
                    raise DailySourceError("TOP40_MAPPED_SECURITY_IDENTITY_MISMATCH:" + row["ticker"])
            held = {ticker for state in accounts.values() for ticker in state["weights"]}
            for sid, state in (states or {}).items():
                if sid not in accounts:
                    continue
                supplied_ids = state.get("security_ids", {})
                if not isinstance(supplied_ids, dict) or any(
                    ticker in supplied_ids and str(supplied_ids[ticker]) != identities.get(ticker)
                    for ticker in accounts[sid]["weights"]):
                    raise DailySourceError("ACCOUNT_HELD_SECURITY_IDENTITY_CHANGED:" + sid)
            if held:
                self._closes(held, signal, identities)
            from scripts.research.a2.portfolio import selected_hgb as hgb
            selected_policy = package.get("policy_id", hgb.LEGACY_POLICY)
            for sid, state in accounts.items():
                if sid not in LEGACY_STRATEGY_IDS:
                    continue
                if sid == "RAW_A2":
                    top = sorted(report.get("ranked_rows", report.get("rows", [])), key=lambda row: row["rank"])[:20]
                    if len(top) != 20 or [row["rank"] for row in top] != list(range(1, 21)):
                        raise DailySourceError("RAW_EXACT_TOP20_REQUIRED")
                    weights = {_ticker(row["ticker"]): _number(row.get("raw_target_weight")) for row in top}
                    if len(weights) != 20 or any(abs(weight - .05) > 1e-12 for weight in weights.values()):
                        raise DailySourceError("FROZEN_RAW_TOP20_EQUAL_WEIGHT_REQUIRED")
                    rows = [{"ticker": ticker, "target_weight": weights.get(ticker, 0),
                             "weight_before": state["weights"].get(ticker, 0)}
                            for ticker in sorted(set(weights) | set(state["weights"]))]
                    application = {"status": "READY", "signal_date": signal, "rows": rows,
                                   "target_cash_weight": 0, "account_basis": "RAW_RULE_TARGET"}
                elif not state["weights"] and state["cash_weight"] == 1:
                    application = deepcopy(package["strategies"][sid]["application"])
                    if application.get("account_basis") != "CASH_START":
                        raise DailySourceError("CASH_START_PACKAGE_REQUIRED")
                else:
                    # Each strategy receives its own book; inference never fits.
                    application = hgb.infer_targets(frame, state=state, source_root=package.get("source_root"),
                                                    policy=selected_policy)[sid]
                if sid != "RAW_A2" and application.get("policy_id", hgb.LEGACY_POLICY) != selected_policy:
                    raise DailySourceError("CURRENT_TARGET_POLICY_MISMATCH:" + sid)
                if application.get("status") != "READY" or application.get("signal_date") != signal:
                    raise DailySourceError("CURRENT_TARGET_UNAVAILABLE:" + sid)
                rows = []
                for row in application["rows"]:
                    ticker = _ticker(row["ticker"])
                    if ticker not in identities:
                        raise DailySourceError("TARGET_SECURITY_IDENTITY_UNKNOWN:" + ticker)
                    target = _number(row["target_weight"])
                    if target > 1:
                        raise DailySourceError("TARGET_WEIGHT_OUT_OF_RANGE")
                    if reset is not None and (target > .10 + 1e-7
                            or _number(row.get("weight_before", 0)) != 0):
                        raise DailySourceError("CASH_RESET_TARGET_CONSTRAINT_VIOLATION")
                    rows.append({**row, "ticker": ticker, "code": "US." + ticker,
                                 "security_id": identities[ticker], "target_weight": target,
                                 "weight_before": state["weights"].get(ticker, 0)})
                if len({row["ticker"] for row in rows}) != len(rows) or len({row["security_id"] for row in rows}) != len(rows):
                    raise DailySourceError("DUPLICATE_TARGET_SECURITY")
                if len({row["ticker"] for row in rows}) != len(rows) or len({row["security_id"] for row in rows}) != len(rows):
                    raise DailySourceError("CONSENSUS_DUPLICATE_TARGET_SECURITY")
                cash = _number(application["target_cash_weight"])
                if abs(sum(row["target_weight"] for row in rows) + cash - 1) > 1e-7:
                    raise DailySourceError("TARGET_WEIGHTS_AND_CASH_MUST_SUM_TO_ONE")
                result["plans"][sid] = {"strategy_id": sid, "status": "READY", "signal_date": signal,
                    "source_date": signal, "execution_date": result["execution_date"], "rows": rows,
                    "target_cash_weight": cash, "cash_weight_before": state["cash_weight"],
                    "account_basis": application.get("account_basis"), "valuation_basis": "SIGNAL_CLOSE",
                    "execution_status": "TARGET_ONLY", "provenance": _PROVENANCE,
                    "broker_action_allowed": False, "model_fit_calls": 0}
                if sid != "RAW_A2" and selected_policy != hgb.LEGACY_POLICY:
                    result["plans"][sid]["policy_id"] = selected_policy
                if reset is not None:
                    result["plans"][sid].update(
                        reset_id=reset["reset_id"], requested_at=reset["requested_at"],
                        account_basis="USER_REQUESTED_POST_LIQUIDATION_CASH_START",
                        target_origin_account_basis="CASH_START",
                        valuation_basis="POST_LIQUIDATION_ASSUMPTION",
                        execution_condition="ACCOUNT_FLAT_AFTER_CONFIRMED_LIQUIDATION")
            result["scores"] = deepcopy({key: value for key, value in package["shared_scores"].items()
                                         if key != "historical"})
            result["source_refs"] = deepcopy(self.refs)
            result["source_hashes"] = deepcopy(package["source_hashes"])
            for plan in result["plans"].values():
                plan["source_refs"] = deepcopy(self.refs)
                plan["source_hashes"] = deepcopy(package["source_hashes"])
                plan["data_gaps"] = []
            result["coverage_gaps"] = {"scope": "UPSTREAM_POOL_EXCLUSIONS_NOT_SCORED",
                                      "coverage": deepcopy(report.get("coverage")),
                                      "mapping_gaps": deepcopy(report.get("universe", {}).get("mapping_gaps", []))}
        except (OSError, KeyError, TypeError, ValueError) as exc:
            result.update(status="BLOCKED", ready=False, execute_now=False, plans={}, scores=None,
                          reason=str(exc) if isinstance(exc, DailySourceError) else "CURRENT_PLAN_UNAVAILABLE:" + type(exc).__name__,
                          reason_code="CURRENT_PLAN_UNAVAILABLE", source_refs=deepcopy(self.refs),
                          data_gaps=exc.data_gaps if isinstance(exc, DailySourceError) else [{"reason": type(exc).__name__}])
        finally:
            # The canonical worker owns this serial stage. _bundle has no
            # object cache; refs and returned plans are small copied receipts.
            hgb.release_runtime()
            reader = sys.modules.get("apps.demo_console.adapters.selected_strategies_reader")
            clear_package_cache = getattr(reader, "clear_cache", None)
            if callable(clear_package_cache):
                clear_package_cache()  # Explicit-path load_package cached the raw bytes and decoded package.
            report = package = frame = application = None
            gc.collect()
        return self._new_plans(result, states, now) if reset is None else result

    def _new_plans(self, result, states, now):
        """Each exact frozen candidate fails independently of existing plans."""
        selected = {sid: value for sid, value in (states or {}).items()
                    if sid in PAPER_CURRENT_IDS}
        statuses = result.setdefault("strategy_status", {})
        for sid in (states or {}):
            if sid not in selected:
                statuses[sid] = {"status": "READY" if sid in result.get("plans", {}) else "BLOCKED"}
        if not selected:
            return result
        from scripts.research.a2.inference import consensus_paper as owner
        signal = result["signal_date"]
        for sid, supplied in selected.items():
            try:
                state = _state(supplied, signal, include_strategy_state=True)
                document, publication_ref = owner.load_publication(self.paths, signal, _iso(_utc(now)),
                    **({"paper_current": True} if sid == "R6_DURATION_TREE" else {}))
                application = owner.infer_application(self.paths, sid, state, document)
                rows = []
                for row in application["rows"]:
                    ticker = _ticker(row["ticker"])
                    security = row.get("security_id") or supplied.get("security_ids", {}).get(ticker)
                    if not security or str(security).strip().lower() in {"nan", "none", "null", "unknown", "unbound", "<na>"}:
                        raise DailySourceError("CONSENSUS_TARGET_SECURITY_ID_REQUIRED:" + ticker)
                    target = _number(row["target_weight"])
                    if target > 1:
                        raise DailySourceError("CONSENSUS_TARGET_WEIGHT_OUT_OF_RANGE")
                    rows.append({**row, "ticker": ticker, "code": "US." + ticker,
                                 "security_id": str(security), "target_weight": target,
                                 "weight_before": state["weights"].get(ticker, 0)})
                if len({row["ticker"] for row in rows}) != len(rows) or len({row["security_id"] for row in rows}) != len(rows):
                    raise DailySourceError("CONSENSUS_DUPLICATE_TARGET_SECURITY")
                cash = _number(application["target_cash_weight"])
                if abs(sum(row["target_weight"] for row in rows) + cash - 1) > 1e-7:
                    raise DailySourceError("CONSENSUS_TARGET_CASH_SUM")
                plan = {**application, "strategy_id": sid, "source_date": signal,
                    "execution_date": result["execution_date"], "rows": rows,
                    "cash_weight_before": state["cash_weight"], "valuation_basis": "SIGNAL_CLOSE",
                    "execution_status": "TARGET_ONLY", "provenance": _PROVENANCE,
                    "broker_action_allowed": False, "model_fit_calls": 0, "data_gaps": [],
                    "source_hashes": {key: value["sha256"] for key, value in application["model_refs"].items()}}
                plan["source_refs"] = {**application["source_refs"], "consensus/publication": publication_ref,
                                       **{"model/" + key: value for key, value in application["model_refs"].items()}}
                result.setdefault("plans", {})[sid] = plan
                result.setdefault("source_refs", {}).update({sid + "/" + key: value for key, value in plan["source_refs"].items()})
                statuses[sid] = {"status": "READY", "signal_date": signal}
            except Exception as exc:
                # Optional candidate inference/backend/resource faults retain
                # every already validated peer plan; the worker stays bounded.
                statuses[sid] = {"status": "BLOCKED", "reason": str(exc), "signal_date": signal}
        if result.get("plans"):
            # Execution still checks its selected strategy's plan and clock.
            completed = _clock_status(_utc(now), signal, self._calendar(_utc(now))[1], self.close_hours, signal, True)
            result.update({key: value for key, value in completed.items() if key not in ("data_gaps", "source_refs")})
            if any(item["status"] == "BLOCKED" for item in statuses.values()):
                result["status"] = "PARTIAL"
            result["data_gaps"] = []
        return result

    def refresh(self):
        from scripts.daily_recommendation import run_update
        result = run_update(self.paths, execute=True, emit_progress=lambda *args, **kwargs: None)
        return {key: result.get(key) for key in ("status", "data_date", "run_id", "report_path", "reason",
                                                "broker_action_allowed")}


def _worker():
    request = json.load(sys.stdin)
    action = request.get("action")
    if action not in {"status", "load", "close_states", "refresh", "main_charts_status"}:
        raise DailySourceError("UNKNOWN_CANONICAL_SOURCE_ACTION")
    # Canonical libraries sometimes print diagnostics. They must not corrupt the
    # JSON protocol or expose provider logs; the caller only receives this schema.
    # Unused diagnostics must not accumulate during a full daily refresh.
    with open(os.devnull, "w", encoding="utf-8") as sink, redirect_stdout(sink):
        if action=="main_charts_status":
            return _main_charts_metadata(request["repo_root"], request["now"], **(
                {'finite_ca_admission_ref': request['finite_ca_admission_ref']} if 'finite_ca_admission_ref' in request else {}))
        source = _CanonicalSource(request["repo_root"])
        arguments = {key: value for key, value in request.items() if key not in {"repo_root", "action"}}
        result = getattr(source, action)(**arguments)
    return result


if __name__ == "__main__":
    # Keep SDK/native and atexit stdout away from the JSON pipe for the entire
    # worker lifetime. Canonical provider files still retain their own logs.
    protocol = os.fdopen(os.dup(sys.stdout.fileno()), "w", encoding="utf-8")
    with open(os.devnull, "w") as quiet:
        os.dup2(quiet.fileno(), sys.stdout.fileno())
    try:
        if sys.argv[1:] != ["--worker"]:
            raise DailySourceError("FIXED_WORKER_ENTRY_REQUIRED")
        payload = {"ok": True, "result": _worker()}
    except Exception as error:
        payload = {"ok": False,
                   "reason": error.reason if isinstance(error, DailySourceError) else "CANONICAL_SOURCE_ERROR:" + type(error).__name__,
                   "data_gaps": getattr(error, "data_gaps", [{"reason": type(error).__name__}]),
                   "source_refs": getattr(error, "source_refs", {})}
    protocol.write(_bytes(payload).decode("utf-8"))
    protocol.flush()
