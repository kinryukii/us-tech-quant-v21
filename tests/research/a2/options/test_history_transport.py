"""Bounded transport counterexamples; every response and credential is synthetic."""
import json
from urllib.parse import parse_qs, quote as urlquote, quote_plus, urlencode, urlsplit

import pytest

from scripts.research.a2.options import historical_quotes as history
from scripts.research.a2.options.contracts import Invalid


@pytest.fixture
def probe():
    path = history.resolve().results_root / history.TEMPLATE / "overnight/20260913T032957JST/reviewed/option_evidence/fixed_probe_plan.json"
    return json.loads(path.read_text(encoding="utf-8"))["selected"][0]


def request(probe, tmp_path, transport, **changes):
    descriptor = history.qualification_requests(probe)[1]
    values = dict(api_key="TEST_ONLY_SECRET", probe=probe, url=descriptor["url"], params=descriptor["params"],
                  state_path=tmp_path / "state.json", cache_root=tmp_path / "cache", now=lambda: 100., transport=transport, sleep=lambda _: None)
    values.update(changes)
    return history.request_massive_history(**values)


def quote(probe, **changes):
    row = dict(sip_timestamp=history.pre2026(probe["start"]).value, bid_price=10., ask_price=10.1, bid_size=3, ask_size=7)
    return row | changes


def next_url(url, original, cursor, **changes):
    query = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in original.items()}
    return url + "?" + urlencode(query | {"cursor": cursor} | changes)


def test_descriptors_keep_original_order_and_do_not_make_economic_plan(probe):
    descriptors = history.qualification_requests(probe)
    assert [item["kind"] for item in descriptors] == ["contracts", "stock_quotes", "stock_trades"]
    assert descriptors[0]["params"]["as_of"] == "2025-02-04"
    assert descriptors[0]["params"]["expired"] is False
    assert descriptors[0]["params"]["expiration_date.lte"] == "2025-04-05"
    option = history.qualification_requests(probe, "O:ADPT250321C00100000")
    assert len(option) == 1 and option[0]["kind"] == "option_quotes"
    with pytest.raises(Invalid):
        history.qualification_requests(probe, "O:AFRM250321C00100000")


@pytest.mark.parametrize("change", [{"underlying_symbol": "OTHER"}, {"start": "2026-02-04T09:44:59-05:00"}])
def test_changed_probe_is_rejected_before_transport_or_state(probe, tmp_path, change):
    calls = []
    with pytest.raises(Invalid):
        request(probe | change, tmp_path, lambda *a, **k: calls.append(a))
    assert not calls and not (tmp_path / "state.json").exists()


def test_missing_credentials_is_no_request_and_no_qualification(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **k: pytest.fail("HTTP sent"), api_key=None)
    assert result["status"] == "NOT_TESTABLE_NO_CREDENTIALS"
    assert result["provider_requests_consumed"] == result["http_requests"] == 0
    assert not result["page_complete"] and result["evidence_grade"] == "UNQUALIFIED"


def test_real_shape_mapping_preserves_display_sizes_and_cache_is_exact(probe, tmp_path):
    calls = []
    def transport(url, **kwargs):
        state = json.loads((tmp_path / "state.json").read_text())
        assert state["attempts"][-1]["status"] == "PENDING_UNKNOWN"
        assert kwargs["allow_redirects"] is False and kwargs["headers"] == {"Accept": "application/json"}
        assert kwargs["api_key"] == "TEST_ONLY_SECRET" and "apiKey" not in kwargs["params"]
        calls.append(url)
        return 200, {"results": [quote(probe, id="fixture-id", unknown_field="UNRECORDED")]}
    result = request(probe, tmp_path, transport)
    assert result["rows"][0]["bid_size"] == 3 and result["rows"][0]["ask_size"] == 7
    assert result["unit_status"] == result["evidence_grade"] == "UNQUALIFIED"
    assert result["entitlement"] == "UNKNOWN" and result["page_complete"]
    reused = request(probe, tmp_path, lambda *a, **k: pytest.fail("Cache sent again"), api_key=None)
    assert reused["http_requests"] == 0 and reused["cached_pages"] == 1 and reused["rows"] == result["rows"]
    assert len(calls) == 1
    assert all("TEST_ONLY_SECRET" not in p.read_text() for p in tmp_path.rglob("*.json"))
    cached = json.loads(next((tmp_path / "cache").glob("*.json")).read_text())
    assert cached["request"]["authentication_method"] == "MASSIVE_QUERY_PARAMETER"


@pytest.mark.parametrize("http_status, expected", [(200, "EMPTY_RESPONSE"), (404, "ENDPOINT_OR_RECORD_NOT_FOUND"), (302, "HTTP_ERROR")])
def test_empty_404_and_redirect_do_not_certify_permissions(probe, tmp_path, http_status, expected):
    result = request(probe, tmp_path, lambda *a, **k: (http_status, {"results": [], "message": "UNRECORDED_PROVIDER_MESSAGE"}))
    assert result["status"] == expected and result["entitlement"] == "UNKNOWN"
    assert result["http_requests"] == 1
    assert all("TEST_ONLY_SECRET" not in p.read_text() for p in tmp_path.rglob("*.json"))


@pytest.mark.parametrize("status, other_path_requests", [(401, 0), (403, 1)])
def test_authentication_stops_all_paths_but_403_isolates_endpoint(probe, tmp_path, status, other_path_requests):
    first = request(probe, tmp_path, lambda *a, **k: (status, {}))
    assert first["http_requests"] == 1
    descriptor = history.qualification_requests(probe)[2]
    result = request(probe, tmp_path, lambda *a, **k: (200, {"results": []}), url=descriptor["url"], params=descriptor["params"])
    assert result["http_requests"] == other_path_requests
    if status == 401:
        assert result["authentication"] == "REJECTED"


def test_pending_attempt_survives_interrupt_without_resend(probe, tmp_path):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        request(probe, tmp_path, interrupted)
    result = request(probe, tmp_path, lambda *a, **k: pytest.fail("Unknown request retried"))
    assert result["status"] == "UNCERTAIN_ATTEMPT_NO_RETRY" and result["provider_requests_consumed"] == 1


def test_transport_exception_is_sanitized_and_not_retried(probe, tmp_path):
    key = 'TEST_ONLY secret +/"字\\end'
    def failed(*args, **kwargs):
        raise RuntimeError("https://api.massive.com/error?" + urlencode({"apiKey": key}))
    result = request(probe, tmp_path, failed, api_key=key)
    assert result["status"] == "TRANSPORT_EXCEPTION"
    resumed = request(probe, tmp_path, lambda *a, **k: pytest.fail("Uncertain request retried"), api_key=key)
    assert resumed["http_requests"] == 0 and resumed["cached_pages"] == 1
    assert all(not any(v in p.read_text() for v in history.secret_variants(key)) for p in tmp_path.rglob("*.json"))


@pytest.mark.parametrize("page_kind", ["other_host", "other_path", "changed_range", "cursor_only", "secret_cursor"])
def test_pagination_scope_and_secret_boundaries(probe, tmp_path, page_kind):
    def transport(url, **kwargs):
        link = next_url(url, kwargs["params"], "next", apiKey="SYNTHETIC_OTHER_TOKEN")
        if page_kind == "other_host":
            link = link.replace("api.massive.com", "evil.invalid")
        elif page_kind == "other_path":
            link = link.replace("/quotes/", "/trades/")
        elif page_kind == "changed_range":
            link = next_url(url, kwargs["params"], "next", **{"timestamp.lte": "1790000000000000000"})
        elif page_kind == "cursor_only":
            link = url + "?cursor=opaque"
        elif page_kind == "secret_cursor":
            link = next_url(url, kwargs["params"], "TEST_ONLY_SECRET")
        return 200, {"results": [quote(probe)], "next_url": link}
    result = request(probe, tmp_path, transport)
    expected = "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED" if page_kind == "secret_cursor" else "PAGINATION_SCOPE_REJECTED"
    assert result["status"] == expected and result["http_requests"] == 1 and not result["page_complete"]
    assert all("TEST_ONLY_SECRET" not in p.read_text() for p in tmp_path.rglob("*.json"))


def test_every_page_consumes_budget_and_resume_is_deterministic(probe, tmp_path):
    original = history.qualification_requests(probe)[1]["params"]
    def transport(url, **kwargs):
        count = len(json.loads((tmp_path / "state.json").read_text())["attempts"])
        return 200, {"results": [quote(probe)], "next_url": next_url(url, original, str(count), apiKey="SYNTHETIC_OTHER_TOKEN")}
    first = request(probe, tmp_path, transport)
    assert first["http_requests"] == 12 and first["row_count"] == 12 and first["status"] == "REQUEST_BUDGET_STOPPED"
    second = request(probe, tmp_path, lambda *a, **k: pytest.fail("Budget exceeded"))
    assert second["http_requests"] == 0 and second["cached_pages"] == 12 and second["rows"] == first["rows"]
    assert second["status"] == first["status"] and not second["page_complete"]
    assert all("SYNTHETIC_OTHER_TOKEN" not in p.read_text() for p in tmp_path.rglob("*.json"))


def test_missing_results_field_is_not_a_confirmed_empty_window(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **k: (200, {}))
    assert result["status"] == "RESPONSE_RESULTS_FIELD_MISSING"
    assert result["page_complete"] is False
    assert result["row_count"] == 0


def test_qualification_page_limit_keeps_incomplete_state_and_reuses_cached_page(probe, tmp_path):
    def transport(url, **kwargs):
        return 200, {"results": [quote(probe)], "next_url": next_url(url, kwargs["params"], "next")}
    first = request(probe, tmp_path, transport, page_limit=1)
    assert first["http_requests"] == 1 and first["row_count"] == 1
    assert first["status"] == "QUALIFICATION_PAGE_LIMIT" and not first["page_complete"]
    resumed = request(probe, tmp_path, lambda *a, **k: pytest.fail("Qualification requested another page"), page_limit=1)
    assert resumed["http_requests"] == 0 and resumed["cached_pages"] == 1
    assert resumed["status"] == first["status"] and not resumed["page_complete"]
    assert resumed["rows"] == first["rows"] and resumed["provider_requests_consumed"] == 1


def test_credential_echo_in_arbitrary_payload_keys_is_rejected_before_persistence(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **k: (200, {"results": [quote(probe)], "TEST_ONLY_SECRET": {"other": 1}}))
    assert result["status"] == "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED" and result["rows"] == []
    assert all("TEST_ONLY_SECRET" not in p.read_text() for p in tmp_path.rglob("*.json"))


def test_out_of_window_response_is_not_cached_as_eligible_data(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **k: (200, {"results": [quote(probe, sip_timestamp=history.pre2026(probe["end"]).value + 1)]}))
    assert result["status"] == "RESPONSE_RANGE_REJECTED" and not result["rows"] and not result["page_complete"]


@pytest.mark.parametrize("payload,entitlement", [({}, "UNKNOWN"), ({"status": "NOT_AUTHORIZED"}, "DENIED_FOR_THIS_PATH")])
def test_403_permission_needs_explicit_structured_evidence(probe, tmp_path, payload, entitlement):
    result = request(probe, tmp_path, lambda *a, **k: (403, payload))
    assert result["entitlement"] == entitlement and result["status"] == "RESOURCE_FORBIDDEN"


def test_rate_limit_stops_provider_without_retrying_other_endpoints(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **k: (429, {}))
    assert result["status"] == "RATE_LIMITED"
    descriptor = history.qualification_requests(probe)[2]
    stopped = request(probe, tmp_path, lambda *a, **k: pytest.fail("Rate limit bypassed"),
                      url=descriptor["url"], params=descriptor["params"])
    assert stopped["status"] == "RATE_LIMITED_PROVIDER_STOPPED" and stopped["http_requests"] == 0


def test_qualified_cache_tampering_fails_before_network(probe, tmp_path):
    request(probe, tmp_path, lambda *a, **k: (200, {"results": [quote(probe)]}))
    artifact = next((tmp_path / "cache").glob("*.json"))
    artifact.write_text("{}")
    with pytest.raises(Invalid, match="QUALIFIED_CACHE_IDENTITY_MISMATCH"):
        request(probe, tmp_path, lambda *a, **k: pytest.fail("Tampered cache bypassed"))


def test_expired_original_time_budget_is_not_reset(probe, tmp_path):
    request(probe, tmp_path, lambda *a, **k: pytest.fail("HTTP sent"), api_key=None)
    result = request(probe, tmp_path, lambda *a, **k: pytest.fail("Deadline reset"), now=lambda: 14500.)
    assert result["status"] == "TIME_BUDGET_STOPPED" and result["http_requests"] == 0


def test_query_authentication_is_added_only_at_wire_boundary(probe, monkeypatch):
    import requests
    descriptor = history.qualification_requests(probe)[0]
    original = dict(descriptor["params"])
    key = 'TEST_ONLY query +/"字\\end'
    class Response:
        status_code = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return None
        def iter_content(self, chunk_size):
            assert chunk_size == 65536
            yield b'{"results": []}'
    def get(url, **kwargs):
        assert url == descriptor["url"] and not urlsplit(url).query
        assert kwargs["params"]["apiKey"] == key and kwargs["params"]["expired"] == "false"
        assert kwargs["headers"] == {"Accept": "application/json"} and kwargs["allow_redirects"] is False
        prepared = requests.Request("GET", url, params=kwargs["params"]).prepare()
        assert parse_qs(urlsplit(prepared.url).query)["apiKey"] == [key]
        return Response()
    monkeypatch.setattr(requests, "get", get)
    status, payload = history._history_get(descriptor["url"], params=descriptor["params"], api_key=key,
        headers={"Accept": "application/json"}, timeout=(5, 30), allow_redirects=False)
    assert (status, payload) == (200, {"results": []}) and descriptor["params"] == original


@pytest.mark.parametrize("encoding", ["raw", "quote", "quote_plus", "json_ascii", "json_unicode", "csv"])
def test_response_credential_variants_are_rejected_before_cache_write(probe, tmp_path, encoding):
    key = 'TEST_ONLY encoded +/"字\\end'
    encoded = {"raw": key, "quote": urlquote(key, safe=""), "quote_plus": quote_plus(key, safe=""),
        "json_ascii": json.dumps(key, ensure_ascii=True)[1:-1],
        "json_unicode": json.dumps(key, ensure_ascii=False)[1:-1], "csv": key.replace('"', '""')}[encoding]
    result = request(probe, tmp_path, lambda *a, **kw: (200, {"results": [quote(probe)], "context": {encoded: "echo"}}), api_key=key)
    assert result["status"] == "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED" and result["rows"] == []
    for artifact in tmp_path.rglob("*.json"):
        history._require_secret_safe(artifact.read_bytes(), key, "TEST_ARTIFACT_LEAKED")


def test_legal_pagination_api_key_is_removed_without_discarding_page(probe, tmp_path):
    key = 'TEST_ONLY next +/"字\\end'
    def transport(url, **kwargs):
        return 200, {"results": [quote(probe)], "next_url": next_url(url, kwargs["params"], "next", apiKey=key)}
    result = request(probe, tmp_path, transport, api_key=key, page_limit=1)
    assert result["status"] == "QUALIFICATION_PAGE_LIMIT" and result["row_count"] == 1
    assert result["http_requests"] == 1 and not result["page_complete"]
    page = json.loads(next((tmp_path / "cache").glob("*.json")).read_text())
    assert page["next_params"]["cursor"] == "next" and "apiKey" not in page["next_params"]
    for artifact in tmp_path.rglob("*.json"):
        history._require_secret_safe(artifact.read_bytes(), key, "TEST_ARTIFACT_LEAKED")


def test_encoded_pagination_cursor_is_rejected_after_auth_parameter_removal(probe, tmp_path):
    key = 'TEST_ONLY cursor +/"字\\end'
    def transport(url, **kwargs):
        return 200, {"results": [quote(probe)],
            "next_url": next_url(url, kwargs["params"], urlquote(key, safe=""), apiKey=key)}
    result = request(probe, tmp_path, transport, api_key=key)
    assert result["status"] == "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED" and result["rows"] == []
    assert result["http_requests"] == 1 and not result["page_complete"]


def test_injected_transport_kwargs_cannot_be_echoed_into_artifacts(probe, tmp_path):
    result = request(probe, tmp_path, lambda *a, **kwargs: (200, {"results": [], "transport": kwargs}))
    assert result["status"] == "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED"
    assert all("TEST_ONLY_SECRET" not in p.read_text() for p in tmp_path.rglob("*.json"))


def test_encoded_credential_in_cached_bytes_is_rejected_before_hash(probe, tmp_path, monkeypatch):
    key = 'TEST_ONLY cache +/"字\\end'
    request(probe, tmp_path, lambda *a, **k: (200, {"results": [quote(probe)]}), api_key=key)
    artifact = next((tmp_path / "cache").glob("*.json"))
    page = json.loads(artifact.read_text())
    page["context"] = json.dumps(key, ensure_ascii=True)[1:-1]
    artifact.write_text(json.dumps(page))
    tainted = artifact.read_bytes()
    original_sha256 = history.hashlib.sha256
    def guarded_hash(data, *args, **kwargs):
        assert data != tainted, "Credential-bearing cache was hashed"
        return original_sha256(data, *args, **kwargs)
    monkeypatch.setattr(history.hashlib, "sha256", guarded_hash)
    with pytest.raises(Invalid, match="CACHE_CONTAINS_CREDENTIAL_NOT_HASHED"):
        request(probe, tmp_path, lambda *a, **k: pytest.fail("Tainted cache triggered HTTP"), api_key=key)


def test_previous_authentication_cache_identity_is_not_relabelled_query_auth(probe, tmp_path):
    request(probe, tmp_path, lambda *a, **k: (200, {"results": []}))
    artifact = next((tmp_path / "cache").glob("*.json"))
    page = json.loads(artifact.read_text())
    page["request"].pop("authentication_method")
    legacy_digest = history.hashlib.sha256(json.dumps(page["request"], sort_keys=True).encode()).hexdigest()
    legacy = artifact.with_name(legacy_digest + ".json")
    artifact.rename(legacy)
    legacy.write_text(json.dumps(page))
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text())
    state["attempts"][0].update(request_sha256=legacy_digest, cache_sha256=history.hashlib.sha256(legacy.read_bytes()).hexdigest())
    state_path.write_text(json.dumps(state))
    result = request(probe, tmp_path, lambda *a, **k: (200, {"results": [quote(probe)]}))
    assert result["http_requests"] == 1 and result["cached_pages"] == 0 and result["row_count"] == 1
    assert result["provider_requests_consumed"] == 2 and legacy.exists()


def test_free_plan_pacing_survives_failure_and_restart_but_cache_does_not_wait(probe, tmp_path):
    clock, waits, calls = [100.], [], []
    def sleep(seconds):
        waits.append(seconds)
        clock[0] += seconds
    def transport(*args, **kwargs):
        calls.append(clock[0])
        clock[0] += 2.
        return 403, {"status": "NOT_AUTHORIZED"}
    first = request(probe, tmp_path, transport, now=lambda: clock[0], sleep=sleep)
    descriptor = history.qualification_requests(probe)[2]
    second = request(probe, tmp_path, transport, now=lambda: clock[0], sleep=sleep,
                     url=descriptor["url"], params=descriptor["params"])
    cached = request(probe, tmp_path, lambda *a, **k: pytest.fail("Cache resent"),
                     now=lambda: clock[0], sleep=lambda _: pytest.fail("Cache waited"))
    assert first["http_requests"] == second["http_requests"] == 1
    assert calls == [100., 114.5] and waits == [12.5]
    assert cached["cached_pages"] == 1
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["attempts"][-1]["completed_epoch"] == 116.5


def test_pacing_cannot_consume_time_reserved_for_bounded_http(probe, tmp_path):
    request(probe, tmp_path, lambda *a, **k: (200, {"results": []}), now=lambda: 100.)
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text())
    state["attempts"][-1]["completed_epoch"] = 14460.
    state_path.write_text(json.dumps(state))
    descriptor = history.qualification_requests(probe)[2]
    result = request(probe, tmp_path, lambda *a, **k: pytest.fail("Deadline crossed"),
                     now=lambda: 14460., sleep=lambda _: pytest.fail("Should stop before waiting"),
                     url=descriptor["url"], params=descriptor["params"])
    assert result["status"] == "TIME_BUDGET_STOPPED" and result["provider_requests_consumed"] == 1


def test_rate_limit_does_not_erase_previously_explicit_denial(probe, tmp_path):
    request(probe, tmp_path, lambda *a, **k: (403, {"status": "NOT_AUTHORIZED"}))
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text())
    state["rate_limited"] = True
    state_path.write_text(json.dumps(state))
    # A different original probe shares the denied endpoint, with no cache hit.
    plan = history.resolve().results_root / history.TEMPLATE / "overnight/20260913T032957JST/reviewed/option_evidence/fixed_probe_plan.json"
    other = json.loads(plan.read_text())["selected"][1]
    result = request(other, tmp_path, lambda *a, **k: pytest.fail("Denied endpoint retried"))
    assert result["status"] == "RATE_LIMITED_PROVIDER_STOPPED"
    assert result["entitlement"] == "DENIED_FOR_THIS_PATH" and result["http_requests"] == 0


def test_corrected_historical_filter_keeps_old_empty_cache_and_consumption(probe, tmp_path):
    descriptor = history.qualification_requests(probe)[0]
    request(probe, tmp_path, lambda *a, **k: (200, {"results": []}),
            url=descriptor["url"], params=descriptor["params"])
    artifact = next((tmp_path / "cache").glob("*.json"))
    page = json.loads(artifact.read_text())
    page["request"]["params"]["expired"] = True
    old_digest = history.hashlib.sha256(json.dumps(page["request"], sort_keys=True).encode()).hexdigest()
    old_cache = artifact.with_name(old_digest + ".json")
    artifact.rename(old_cache)
    old_cache.write_text(json.dumps(page))
    original_bytes = old_cache.read_bytes()
    state_path = tmp_path / "state.json"
    state = json.loads(state_path.read_text())
    state["attempts"][0].update(request_sha256=old_digest, cache_sha256=history.hashlib.sha256(original_bytes).hexdigest())
    state_path.write_text(json.dumps(state))
    calls = []
    def transport(url, **kwargs):
        calls.append(kwargs["params"])
        return 200, {"results": []}
    result = request(probe, tmp_path, transport, url=descriptor["url"], params=descriptor["params"])
    assert result["http_requests"] == 1 and result["cached_pages"] == 0
    assert result["provider_requests_consumed"] == 2 and old_cache.read_bytes() == original_bytes
    assert calls[0]["expired"] is False and calls[0]["as_of"] == "2025-02-04"
