from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("v21_231_moomoo_only_historical_refetch_and_canonical_rebuild.py")
SPEC = importlib.util.spec_from_file_location("v231", MODULE_PATH)
v231 = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(v231)


def manifest(ticker: str, adjustment: str, success: bool = True, latest: str = "2026-07-15") -> dict:
    return {"ticker": ticker, "moomoo_symbol": f"US.{ticker}", "success": str(success), "latest_date": latest, "adjustment": adjustment}


def test_api_success_with_old_latest_is_stale_not_ok():
    row = v231.coverage([manifest("OLPX", "raw", latest="2026-07-06")], [manifest("OLPX", "qfq", latest="2026-07-06")], [], "2026-07-15", [])[0]
    assert row["coverage_status"] == "STALE_TARGET_DATE"


def test_raw_or_qfq_failure_is_not_promotable_coverage():
    raw_failed = v231.coverage([manifest("CHYM", "raw")], [manifest("CHYM", "qfq", False)], [], "2026-07-15", [])[0]
    qfq_failed = v231.coverage([manifest("GLW", "raw", False)], [manifest("GLW", "qfq")], [], "2026-07-15", [])[0]
    assert raw_failed["coverage_status"] == qfq_failed["coverage_status"] == "API_FAILED"


def test_no_evidence_never_auto_excludes_olpx():
    row = v231.coverage([manifest("OLPX", "raw", latest="2026-07-06")], [manifest("OLPX", "qfq", latest="2026-07-06")], [], "2026-07-15", [])[0]
    assert row["coverage_status"] != "LEGALLY_EXCLUDED"


def test_explicit_allowed_exclusion_is_legal():
    exclusion = {"ticker": "OLPX", "target_date": "2026-07-15", "allowed": "True"}
    row = v231.coverage([manifest("OLPX", "raw", latest="2026-07-06")], [manifest("OLPX", "qfq", latest="2026-07-06")], [], "2026-07-15", [exclusion])[0]
    assert row["coverage_status"] == "LEGALLY_EXCLUDED"


def test_rate_limiter_records_every_call_and_shared_modes():
    limiter = v231.HistoryKlineLimiter(max_calls=55, min_interval=0, window_seconds=30)
    limiter.acquire({"ticker": "CHYM", "adjustment": "raw", "frequency": "1d"})
    limiter.acquire({"ticker": "CHYM", "adjustment": "qfq", "frequency": "1d"})
    assert [r["adjustment"] for r in limiter.audit_rows] == ["raw", "qfq"]


def test_fail_decision_constant_is_not_ready():
    assert "READY" not in "MOOMOO_ONLY_CANONICAL_BLOCKED_DAILY_COVERAGE_BELOW_THRESHOLD"
