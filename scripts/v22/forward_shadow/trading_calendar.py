"""Deterministic forward-shadow US session calendar bound to frozen R26A2 rules."""

from __future__ import annotations

import hashlib
import importlib
import importlib.machinery
import importlib.util
import json
import sys
from datetime import date, datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd


class TradingCalendarError(RuntimeError):
    pass


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _load_frozen_calendar_class(source: Path):
    """Load the existing package without adding a repository path to sys.path."""
    fast3_src = source.parents[2]
    package_spec = importlib.machinery.PathFinder.find_spec("fast3", [str(fast3_src)])
    if package_spec is None or package_spec.loader is None:
        raise TradingCalendarError("FROZEN_FAST3_PACKAGE_NOT_LOADABLE")
    if "fast3" not in sys.modules:
        package = importlib.util.module_from_spec(package_spec)
        sys.modules["fast3"] = package
        package_spec.loader.exec_module(package)
    module = importlib.import_module("fast3.economics.executable_payoff_ledger_calendar_hard_r26a2")
    return module._FrozenNyseHolidayCalendar


class ForwardShadowTradingCalendarProvider:
    """NYSE/Nasdaq normal-session eligibility; early closes remain sessions."""

    def __init__(self, contract_path: Path):
        self.contract_path = contract_path.resolve()
        self.contract = json.loads(self.contract_path.read_text(encoding="utf-8"))
        if self.contract.get("calendar_id") != "A2_FORWARD_SHADOW_US_SESSIONS_R1":
            raise TradingCalendarError("TRADING_CALENDAR_ID_MISMATCH")
        self.start = date.fromisoformat(self.contract["start_date"])
        self.end = date.fromisoformat(self.contract["end_date"])
        self.timezone = ZoneInfo(self.contract["timezone"])
        self.regular_close = time.fromisoformat(self.contract["regular_close_time"])
        source = Path(self.contract["rules_source"])
        if not source.is_file() or _file_sha256(source) != self.contract["rules_source_sha256"]:
            raise TradingCalendarError("FROZEN_CALENDAR_RULE_SOURCE_SHA256_MISMATCH")
        calendar_class = _load_frozen_calendar_class(source)
        days = pd.date_range(self.start, self.end, freq="D")
        holidays = {item.date() for item in calendar_class().holidays(start=self.start, end=self.end)}
        self.sessions = tuple(str(item.date()) for item in days if item.weekday() < 5 and item.date() not in holidays)
        if len(self.sessions) != int(self.contract["session_count"]):
            raise TradingCalendarError("TRADING_CALENDAR_SESSION_COUNT_MISMATCH")
        if _canonical_sha256(list(self.sessions)) != self.contract["sessions_sha256"]:
            raise TradingCalendarError("TRADING_CALENDAR_SESSIONS_SHA256_MISMATCH")

    @property
    def calendar_id(self) -> str:
        return str(self.contract["calendar_id"])

    @property
    def calendar_sha256(self) -> str:
        return _file_sha256(self.contract_path)

    def is_session(self, value: str | date) -> bool:
        day = date.fromisoformat(value) if isinstance(value, str) else value
        if day < self.start or day > self.end:
            raise TradingCalendarError("TRADING_DATE_OUTSIDE_BOUND_CALENDAR_HORIZON")
        return str(day) in self.sessions

    def completed_session_metadata(self, target_date: str, as_of_timestamp: str, timezone: str) -> dict[str, object]:
        target = date.fromisoformat(target_date)
        parsed = datetime.fromisoformat(as_of_timestamp.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
        as_of_ny = parsed.astimezone(self.timezone)
        completed = []
        for value in self.sessions:
            day = date.fromisoformat(value)
            close = datetime.combine(day, self.regular_close, self.timezone)
            if close <= as_of_ny:
                completed.append(value)
        latest = completed[-1] if completed else None
        target_close = datetime.combine(target, self.regular_close, self.timezone)
        return {
            "latest_completed_us_session": latest,
            "target_session_completed": self.is_session(target) and target_close <= as_of_ny,
            "as_of_timestamp": parsed.isoformat(),
            "as_of_timezone": timezone,
            "market_timezone": str(self.timezone),
        }

    def lag_sessions(self, canonical_latest_date: str, latest_completed_session: str | None) -> int | None:
        if latest_completed_session is None or canonical_latest_date not in self.sessions:
            return None
        start = self.sessions.index(canonical_latest_date)
        end = self.sessions.index(latest_completed_session)
        return max(0, end - start)
