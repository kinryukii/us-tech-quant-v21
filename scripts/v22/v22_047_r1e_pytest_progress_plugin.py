"""Pytest progress writer used by the bounded R1E full-repository probe."""
from __future__ import annotations
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE = {"collected": 0, "completed": 0, "passed": 0, "failed": 0, "skipped": 0, "failures": [], "collection_errors": []}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def path() -> Path | None:
    value = os.environ.get("R1E_PYTEST_PROGRESS_PATH", "")
    return Path(value) if value else None


def write() -> None:
    target = path()
    if target is None:
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(STATE)
    payload["timestamp_utc"] = now()
    payload["progress_ratio"] = STATE["completed"] / STATE["collected"] if STATE["collected"] else 0.0
    fd, temp = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp, target)


def pytest_collection_finish(session):
    STATE["collected"] = len(session.items)
    write()


def pytest_collectreport(report):
    if report.failed:
        STATE["collection_errors"].append({"nodeid": report.nodeid, "error": str(report.longrepr)[:4000]})
        write()


def pytest_runtest_logreport(report):
    if report.when != "call":
        if report.failed:
            STATE["failures"].append({"nodeid": report.nodeid, "phase": report.when, "error": str(report.longrepr)[:4000]})
            STATE["failed"] += 1
            STATE["completed"] += 1
            write()
        return
    STATE["completed"] += 1
    if report.passed:
        STATE["passed"] += 1
    elif report.skipped:
        STATE["skipped"] += 1
    else:
        STATE["failed"] += 1
        STATE["failures"].append({"nodeid": report.nodeid, "phase": report.when, "error": str(report.longrepr)[:4000]})
    write()

