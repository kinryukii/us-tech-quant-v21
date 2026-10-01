"""Frozen USTQ inputs for explicitly authorised paper accounts.

The public facade has no SDK dependencies. Its fixed-action worker runs in the
canonical Python environment, reads existing data, and never fits a model. Only
``refresh`` invokes the existing, globally locked recommendation updater.
Upstream ``broker_action_allowed=False`` remains unchanged; these are local
paper weight plans, not broker instructions or share quantities.
"""
from __future__ import annotations

from contextlib import redirect_stdout
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from zoneinfo import ZoneInfo


STRATEGY_IDS = ("RAW_A2", "HGB_DIAG_5", "HGB_FACTOR_5")
OPEN_WINDOW_SECONDS = 60
_TICKER = re.compile(r"[A-Z][A-Z0-9]{0,9}(?:\.[A-Z])?")
_HASH = re.compile(r"[0-9a-f]{64}")
_PROVENANCE = "EXPLICIT_LOCAL_PAPER_ADAPTER_FROZEN_USTQ"


class DailySourceError(ValueError):
    def __init__(self, reason, *, data_gaps=None, source_refs=None):
        super().__init__(reason)
        self.reason = str(reason)
        self.data_gaps = data_gaps or [{"reason": self.reason}]
        self.source_refs = source_refs or {}


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


def _state(state, signal_date):
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
    return {"weights": weights, "cash_weight": cash, "signal_date": signal_date,
            "valuation_basis": "SIGNAL_CLOSE"}


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

    def _call(self, action, **values):
        request = {"action": action, "repo_root": str(self.repo_root), **values}
        try:
            result = subprocess.run([str(self.python_exe), "-X", "utf8", "-B", str(Path(__file__).resolve()),
                                     "--worker"], input=_bytes(request).decode("utf-8"),
                                    capture_output=True, encoding="utf-8", timeout=None if action == "refresh" else 300,
                                    check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            response = json.loads(result.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
            # Do not echo logs, environment variables, or potentially sensitive provider output.
            raise DailySourceError("CANONICAL_SOURCE_WORKER_UNAVAILABLE:" + type(exc).__name__) from exc
        if result.returncode or not response.get("ok"):
            raise DailySourceError(response.get("reason", "CANONICAL_SOURCE_WORKER_FAILED"),
                                   data_gaps=response.get("data_gaps"), source_refs=response.get("source_refs"))
        return response["result"]

    def status(self, now=None):
        return self._call("status", now=_iso(_utc(now)) if now is not None else None)

    def load(self, states, now=None):
        _account_ids(states)
        result = self._call("load", states=states, now=_iso(_utc(now)) if now is not None else None)
        if result.get("plans") and self.runtime_root is not None:
            self._archive(result, states)
        return result

    def close_states(self, books, signal_date):
        _account_ids(books)
        return self._call("close_states", books=books, signal_date=_day(signal_date))

    def refresh(self):
        """Run the original updater once; it owns provider access and its OS lock."""
        return self._call("refresh")

    def _archive(self, result, states):
        # Different accounts/brokers have separate runtime roots. Volatile clock
        # fields are intentionally excluded from the immutable daily payload.
        runtime_root = self.runtime_root.resolve()
        destination = (runtime_root / _day(result["source_date"]) / "plans.json").resolve()
        if any(runtime_root == root or runtime_root.is_relative_to(root) for root in self._read_only_roots):
            raise DailySourceError("PAPER_ARCHIVE_MUST_BE_OUTSIDE_CANONICAL_REPO")
        if runtime_root == self.daily_root or not destination.is_relative_to(self.daily_root):
            raise DailySourceError("PAPER_ARCHIVE_REQUIRES_DAILY_ROOT")
        stable = {key: deepcopy(result.get(key)) for key in (
            "source_date", "execution_date", "next_open_utc", "next_close_utc", "plans",
            "scores", "source_refs", "source_hashes", "coverage_gaps", "provenance", "model_fit_calls")}
        stable["states"] = {sid: _state(state, result["source_date"]) for sid, state in states.items()}
        raw = _bytes(stable)
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
                if destination.read_bytes() != raw:
                    raise DailySourceError("IMMUTABLE_PAPER_PLAN_CONFLICT", source_refs=result.get("source_refs"))
        finally:
            temporary.unlink()
        result["archive"] = {"path": str(destination), "sha256": hashlib.sha256(raw).hexdigest()}


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
        package_path = Path(os.environ.get("USTQ_SELECTED_HGB_PACKAGE") or
                            self.paths.daily_root / "A2_selected_hgb/latest.json")
        package = load_package(package_path)
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
        qualified_lineage, lineage_ref = None, None
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
                            or entry.get("adapter_sha256") != original.ADAPTER_SHA
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
                    self.refs["close/" + ticker] = {**massive_ref, "signal_date": signal,
                        "price_basis": "RAW", "currency": "USD", "source": "MASSIVE_GROUPED",
                        "currency_basis": "MASSIVE_US_GROUPED_MARKET_RAW_USD", "provider_code": ticker,
                        "security_id": identities[ticker], "row_source_id": row["source_id"],
                        "observed_at": row["observed_at"], "inputs": proof["raw_inputs"],
                        "qualification_lineage": lineage_ref, "native_anchor": native_anchor,
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
            result[sid] = {"weights": {ticker: value / equity for ticker, value in values.items()},
                "cash_weight": cash / equity, "signal_date": signal, "valuation_basis": "SIGNAL_CLOSE",
                "equity": equity, "prices": {"US." + ticker: prices["US." + ticker] for ticker in positions},
                "security_ids": {ticker: identities[ticker] for ticker in positions},
                "source_refs": deepcopy(self.refs), "close_asof_utc": _iso(hours[signal][1]),
                "price_basis": "RAW_USD_CLOSE", "provenance": _PROVENANCE}
        return result

    def load(self, states, now=None):
        _account_ids(states)
        result = self.status(now)
        result["plans"], result["scores"] = {}, None
        # A stale complete source may still be displayed, but only its exact
        # original date/state is accepted. It can never become executable.
        if result["source_date"] is None or result["data_gaps"]:
            return result
        try:
            report, package, frame = self._bundle(full=True)
            signal = report["data_date"]
            accounts = {sid: _state(state, signal) for sid, state in states.items()}
            identities = self._identities(report)
            for row in report.get("ranked_rows", report.get("rows", [])):
                if row["rank"] <= 40 and identities.get(row["ticker"]) != str(row["security_id"]):
                    raise DailySourceError("TOP40_MAPPED_SECURITY_IDENTITY_MISMATCH:" + row["ticker"])
            held = {ticker for state in accounts.values() for ticker in state["weights"]}
            for sid, state in states.items():
                supplied_ids = state.get("security_ids", {})
                if not isinstance(supplied_ids, dict) or any(
                    ticker in supplied_ids and str(supplied_ids[ticker]) != identities.get(ticker)
                    for ticker in accounts[sid]["weights"]):
                    raise DailySourceError("ACCOUNT_HELD_SECURITY_IDENTITY_CHANGED:" + sid)
            if held:
                self._closes(held, signal, identities)
            from scripts.research.a2.portfolio import selected_hgb as hgb
            for sid, state in accounts.items():
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
                    application = hgb.infer_targets(frame, state=state, source_root=package.get("source_root"))[sid]
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
                    rows.append({**row, "ticker": ticker, "code": "US." + ticker,
                                 "security_id": identities[ticker], "target_weight": target,
                                 "weight_before": state["weights"].get(ticker, 0)})
                if len({row["ticker"] for row in rows}) != len(rows) or len({row["security_id"] for row in rows}) != len(rows):
                    raise DailySourceError("DUPLICATE_TARGET_SECURITY")
                cash = _number(application["target_cash_weight"])
                if abs(sum(row["target_weight"] for row in rows) + cash - 1) > 1e-7:
                    raise DailySourceError("TARGET_WEIGHTS_AND_CASH_MUST_SUM_TO_ONE")
                result["plans"][sid] = {"strategy_id": sid, "status": "READY", "signal_date": signal,
                    "source_date": signal, "execution_date": result["execution_date"], "rows": rows,
                    "target_cash_weight": cash, "cash_weight_before": state["cash_weight"],
                    "account_basis": application.get("account_basis"), "valuation_basis": "SIGNAL_CLOSE",
                    "execution_status": "TARGET_ONLY", "provenance": _PROVENANCE,
                    "broker_action_allowed": False, "model_fit_calls": 0}
            result["scores"] = deepcopy(package["shared_scores"])
            result["scores"].pop("historical", None)
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
        return result

    def refresh(self):
        from scripts.daily_recommendation import run_update
        result = run_update(self.paths, execute=True, emit_progress=lambda *args, **kwargs: None)
        return {key: result.get(key) for key in ("status", "data_date", "run_id", "report_path", "reason",
                                                "broker_action_allowed")}


def _worker():
    request = json.load(sys.stdin)
    action = request.get("action")
    if action not in {"status", "load", "close_states", "refresh"}:
        raise DailySourceError("UNKNOWN_CANONICAL_SOURCE_ACTION")
    # Canonical libraries sometimes print diagnostics. They must not corrupt the
    # JSON protocol or expose provider logs; the caller only receives this schema.
    with redirect_stdout(io.StringIO()):
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
