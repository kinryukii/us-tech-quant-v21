"""Qualification fixtures are synthetic and never issue an economic request."""
import pandas as pd
import pytest

from scripts.research.a2.options.contracts import Invalid
from scripts.research.a2.options.historical_quotes import classify_http, probe_plan, validate_history_request


def test_plan_uses_original_identity_order_independent_of_holdings_or_returns():
    rows = []
    for month in (2, 5, 8):
        for uid in ("D", "C", "B", "A"):
            rows.append(dict(decision_id=f"{month}:{uid}", signal_date=f"2025-{month:02d}-03",
                             underlying_uid=uid, ticker=uid, planned_entry=f"2025-{month:02d}-04T09:30:00-05:00"))
    frame = pd.DataFrame(rows)
    plan = probe_plan(frame)
    changed = frame.sample(frac=1, random_state=7).assign(future_holding=False, return_5=999.)
    assert plan == probe_plan(changed)
    assert len(plan) == 9
    assert [x["underlying_uid"] for x in plan] == ["A", "B", "C"] * 3
    assert all(x["contract_id"] is None for x in plan)


@pytest.mark.parametrize("status,state", [(None, "NOT_TESTABLE"), (200, "EMPTY_RESPONSE"),
    (401, "AUTHENTICATION_REJECTED"), (403, "RESOURCE_FORBIDDEN"),
    (404, "ENDPOINT_OR_RECORD_NOT_FOUND"), (429, "RATE_LIMITED")])
def test_http_outcomes_are_not_collapsed_into_no_entitlement(status, state):
    value = classify_http(status)
    assert value["response_state"] == state
    assert value["entitlement"] == "UNKNOWN"


def test_permission_denial_stops_only_that_permission_path():
    assert classify_http(401)["stop_permission_path"]
    assert not classify_http(403)["stop_permission_path"]
    value = classify_http(403, permission_explicit=True)
    assert value["stop_permission_path"]
    assert value["entitlement"] == "DENIED_FOR_THIS_PATH"


@pytest.mark.parametrize("response_feed", ["", "opra", "indicative"])
def test_feed_parameter_or_echo_never_upgrades_to_real_quotes(response_feed):
    value = classify_http(200, row_count=2, requested_feed="opra", response_feed=response_feed)
    assert value["evidence_grade"] != "REAL_HISTORICAL_QUOTES"
    assert value["coverage"] == "RECORDS_OBSERVED"
    assert value["entitlement"] == "UNKNOWN"


def test_request_id_is_hashed_not_echoed():
    value = classify_http(403, request_id="sensitive-request-id")
    assert value["request_id_sha256_16"] and "sensitive" not in str(value)


def request():
    start, end = "2025-02-04T14:44:59Z", "2025-02-04T14:46:01Z"
    return dict(url="https://api.massive.com/v3/quotes/O:TEST250321C00100000",
                params={"limit": 100, "timestamp.gte": str(pd.Timestamp(start).value),
                        "timestamp.lte": str(pd.Timestamp(end).value)},
                feed="PROVIDER_FIXED_FEED_SOURCE_UNVERIFIED", start=start, end=end)


def test_narrow_request_boundary_accepts_explicit_historical_window():
    validate_history_request(**request())


@pytest.mark.parametrize("change", [
    {"url": "https://evil.example/v3/quotes/O:TEST250321C00100000"},
    {"url": "https://api.massive.com/v3/quotes/latest"},
    {"url": "https://api.massive.com/v3/quotes/O:TEST250321C00100000?apiKey=secret"},
    {"feed": ""}, {"end": "2026-01-02T14:46:01Z"},
    {"params": {"limit": 100, "timestamp.gte": "1", "timestamp.lte": "2"}},
])
def test_out_of_bound_requests_rejected_before_any_transport(change):
    with pytest.raises(Invalid):
        validate_history_request(**(request() | change))
