"""Bounded R1 option qualification evidence; no broker calls or invented BBO.

The existing expression engine remains the only economic implementation. This
module records actual endpoint/credential boundaries and deterministic probe
objects without promoting documentation or request parameters into entitlement.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

import pandas as pd

from scripts.common.storage_paths import resolve
from .contracts import TEMPLATE, Invalid, pre2026, require

ENV_NAMES = ("APCA_API_KEY_ID", "APCA_API_SECRET_KEY", "ALPACA_API_KEY",
             "ALPACA_SECRET_KEY", "MASSIVE_API_KEY", "POLYGON_API_KEY")
MASSIVE_AUTH_METHOD = "MASSIVE_QUERY_PARAMETER"
MIN_SECONDS_BETWEEN_REQUESTS = 12.5  # Existing successful R3 free-plan pacing.
DOCS = {
    "alpaca_history": "https://docs.alpaca.markets/us/docs/historical-option-data",
    "alpaca_guide": "https://alpaca.markets/learn/fetch-historical-data",
    "alpaca_sdk": "https://raw.githubusercontent.com/alpacahq/alpaca-py/master/alpaca/data/historical/option.py",
    "alpaca_metadata": "https://docs.alpaca.markets/us/reference/get-options-contracts",
    "massive_metadata": "https://massive.com/docs/rest/options/contracts/all-contracts",
    "massive_quotes": "https://massive.com/docs/rest/options/trades-quotes/quotes",
}


def credential_presence() -> dict:
    """Only conventional, named environment slots; never enumerate secrets."""
    return {name: bool(os.environ.get(name)) for name in ENV_NAMES}


def probe_plan(panel: pd.DataFrame) -> list[dict]:
    """First three original identities in each fixed month; no returns/holdings."""
    columns = ["decision_id", "signal_date", "underlying_uid", "ticker", "planned_entry"]
    selected = panel[columns].copy()
    require(not selected.decision_id.duplicated().any(), "DUPLICATE_PROBE_OPPORTUNITY")
    selected["signal_date"] = pd.to_datetime(selected.signal_date)
    require(selected.signal_date.notna().all() and
            selected.signal_date.lt(pd.Timestamp("2026-01-01")).all(), "PROBE_SIGNAL_CUTOFF")
    selected = selected.sort_values(["signal_date", "underlying_uid", "decision_id"])
    rows = []
    for month in ("2025-02", "2025-05", "2025-08"):
        subset = selected[selected.signal_date.dt.strftime("%Y-%m").eq(month)].head(3)
        for order, item in enumerate(subset.to_dict("records"), 1):
            entry = pre2026(item["planned_entry"]).tz_convert("America/New_York")
            # This is a data-qualification window only, not a timing conversion
            # of the close-signal/next-open stock branch into an option replay.
            start = entry.normalize() + pd.Timedelta(hours=9, minutes=44, seconds=59)
            end = entry.normalize() + pd.Timedelta(hours=9, minutes=46, seconds=1)
            pre2026(start); pre2026(end)
            rows.append({"month": month, "candidate_order": order,
                         "decision_id": item["decision_id"], "underlying_uid": item["underlying_uid"],
                         "underlying_symbol": item["ticker"], "signal_date": str(item["signal_date"].date()),
                         "start": start.isoformat(), "end": end.isoformat(), "timezone": "America/New_York",
                         "contract_id": None, "contract_identity": "NOT_YET_ESTABLISHED",
                         "metadata_page_size": 100, "quote_page_size": 100,
                         "selection_rule": "SIGNAL_DATE_UID_DECISION_ID_ASC_NO_OUTCOME_ACCESS",
                         "purpose": "ENDPOINT_QUALIFICATION_ONLY_NOT_ECONOMIC_REPLAY"})
    return rows


def classify_http(status: int | None, *, row_count: int = 0, request_id: str = "",
                  requested_feed: str = "", response_feed: str = "", permission_explicit: bool = False) -> dict:
    """Response facts only. A feed parameter or 200 never self-certifies BBO."""
    require(row_count >= 0, "NEGATIVE_RESPONSE_ROWS")
    state = {None: "NOT_TESTABLE", 200: "ROWS_RETURNED" if row_count else "EMPTY_RESPONSE",
             401: "AUTHENTICATION_REJECTED", 403: "RESOURCE_FORBIDDEN",
             404: "ENDPOINT_OR_RECORD_NOT_FOUND", 429: "RATE_LIMITED"}.get(status, "HTTP_ERROR")
    auth = "AUTHENTICATED_ENDPOINT_RESPONSE" if status == 200 else (
        "REJECTED" if status == 401 else "UNKNOWN")
    return {"http_status": status, "response_state": state, "authentication": auth,
            "entitlement": "DENIED_FOR_THIS_PATH" if status == 403 and permission_explicit else "UNKNOWN",
            "coverage": "RECORDS_OBSERVED" if status == 200 and row_count else "UNKNOWN",
            "row_count": row_count, "requested_feed": requested_feed, "response_feed": response_feed,
            "evidence_grade": "INDICATIVE_OR_AGGREGATE" if response_feed.lower() == "indicative" else "UNQUALIFIED",
            "source_evidence": "NOT_ESTABLISHED_BY_REQUEST_FEED",
            "stop_permission_path": status == 401 or (status == 403 and permission_explicit),
            "request_id_sha256_16": hashlib.sha256(request_id.encode()).hexdigest()[:16] if request_id else None}


def validate_history_request(url: str, params: dict, *, feed: str, start: str, end: str,
                             probe: dict | None = None) -> None:
    """Narrow Massive boundary for a future qualified request, never latest."""
    target = urlsplit(url)
    require(target.scheme == "https" and target.netloc == "api.massive.com" and
            not target.query and not target.fragment, "HISTORY_HOST_OR_URL_BOUNDARY")
    require(bool(feed) and type(params.get("limit")) is int and 1 <= params["limit"] <= 100,
            "EXPLICIT_FEED_AND_PAGE_SIZE_REQUIRED")
    first, last = pre2026(start), pre2026(end)
    require(first < last and (last - first) <= pd.Timedelta(minutes=2), "NARROW_HISTORY_WINDOW_REQUIRED")
    require(not any(str(k).lower() in {"apikey", "token", "authorization"} for k in params), "SECRET_IN_QUERY")
    if target.path == "/v3/reference/options/contracts":
        require(bool(params.get("underlying_ticker")) and params.get("contract_type") == "call" and
                params.get("as_of") == str(first.tz_convert("America/New_York").date()) and
                isinstance(params.get("expired"), bool), "HISTORICAL_CONTRACT_SCOPE_REQUIRED")
        require(params.get("expiration_date.gte") and params.get("expiration_date.lte"), "EXPIRY_RANGE_REQUIRED")
    else:
        option_path = target.path.startswith("/v3/quotes/O:") and "/" not in target.path[len("/v3/quotes/"):]
        stock_path = probe is not None and target.path in (
            "/v3/quotes/" + probe["underlying_symbol"], "/v3/trades/" + probe["underlying_symbol"])
        require(option_path or stock_path, "HISTORY_ENDPOINT_NOT_VERIFIED")
        require(str(params.get("timestamp.gte")) == str(first.value) and
                str(params.get("timestamp.lte")) == str(last.value), "QUOTE_TIME_RANGE_MISMATCH")


def _bound_probe(probe: dict) -> None:
    plan = resolve().results_root / TEMPLATE / "overnight/20260913T032957JST/reviewed/option_evidence/fixed_probe_plan.json"
    raw = plan.read_bytes()
    require(hashlib.sha256(raw).hexdigest() == "c71e8ee8701d0c3e8cd339e53eb4ccb4d734c6b519da635328f7e48922b784c5",
            "FROZEN_PROBE_PLAN_CHANGED")
    require(probe in json.loads(raw)["selected"], "NOT_ORIGINAL_PROBE")


def qualification_requests(probe: dict, option_ticker: str | None = None) -> list[dict]:
    """Qualification only; these nine objects are never an economic sample."""
    _bound_probe(probe)
    day = pre2026(probe["start"]).tz_convert("America/New_York").normalize()
    window = {"timestamp.gte": str(pre2026(probe["start"]).value),
              "timestamp.lte": str(pre2026(probe["end"]).value), "limit": 100,
              "sort": "timestamp", "order": "asc"}
    symbol = probe["underlying_symbol"]
    if option_ticker is not None:
        match = re.fullmatch(r"O:" + re.escape(symbol) + r"(\d{6})C\d{8}", option_ticker)
        require(match is not None, "OPTION_PROBE_IDENTITY")
        expiry = datetime.strptime(match[1], "%y%m%d").date()
        require(30 <= (expiry - day.date()).days <= 60, "OPTION_PROBE_EXPIRY")
        return [{"kind": "option_quotes", "url": "https://api.massive.com/v3/quotes/" + option_ticker, "params": window}]
    metadata = {"underlying_ticker": symbol, "as_of": str(day.date()), "expired": False,
                "contract_type": "call", "expiration_date.gte": str((day + pd.Timedelta(days=30)).date()),
                "expiration_date.lte": str((day + pd.Timedelta(days=60)).date()), "limit": 100}
    return [{"kind": "contracts", "url": "https://api.massive.com/v3/reference/options/contracts", "params": metadata},
            {"kind": "stock_quotes", "url": "https://api.massive.com/v3/quotes/" + symbol, "params": dict(window)},
            {"kind": "stock_trades", "url": "https://api.massive.com/v3/trades/" + symbol, "params": dict(window)}]


def secret_variants(secret: str) -> tuple[str, ...]:
    """Reuse R3's pure in-memory credential encodings; never persist the needles."""
    require(bool(secret), "SECRET_VARIANTS_NEEDLE_EMPTY")
    variants = {secret, quote(secret, safe=""), quote_plus(secret, safe=""),
                urlencode({"apiKey": secret}).partition("=")[2],
                json.dumps(secret, ensure_ascii=False)[1:-1], json.dumps(secret, ensure_ascii=True)[1:-1],
                secret.replace('"', '""')}
    return tuple(sorted((value for value in variants if value), key=len, reverse=True))


def _require_secret_safe(value, secret: str | None, reason: str) -> None:
    if not secret:
        return
    variants, pending = secret_variants(secret), [value]
    while pending:
        item = pending.pop()
        if isinstance(item, bytes):
            text = item.decode("utf-8", errors="replace")
            require(not any(variant in text for variant in variants), reason)
            try:
                pending.append(json.loads(text))
            except ValueError:
                pass
        elif isinstance(item, str):
            require(not any(variant in item for variant in variants), reason)
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, (list, tuple)):
            pending.extend(item)


def _write_json(path: Path, value: dict, *, api_key: str | None = None) -> None:
    serialized = json.dumps(value, sort_keys=True, indent=2) + "\n"
    _require_secret_safe(serialized.encode("utf-8"), api_key, "OUTPUT_CONTAINS_CREDENTIAL_NOT_PERSISTED")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(path)


def _history_get(url: str, *, params: dict, api_key: str, headers: dict, **kwargs) -> tuple[int, dict]:
    import requests
    require(bool(api_key), "MASSIVE_CREDENTIAL_MISSING")
    require(not any(key.lower() == "authorization" for key in headers), "BEARER_AUTH_NOT_THIS_REQUEST")
    # R3 query authentication exists only at the wire boundary. The caller's
    # scope, attempt identity and cache keys retain the original safe parameters.
    wire_params = {key: str(value).lower() if isinstance(value, bool) else value for key, value in params.items()}
    wire_params["apiKey"] = api_key
    with requests.get(url, params=wire_params, headers=headers, stream=True, **kwargs) as response:
        chunks, count = [], 0
        for chunk in response.iter_content(65536):
            count += len(chunk)
            require(count <= 2 * 1024 * 1024, "RESPONSE_SIZE_LIMIT")
            chunks.append(chunk)
        try:
            payload = json.loads(b"".join(chunks))
        except (ValueError, UnicodeError):
            payload = {}
        return response.status_code, payload


def _remove_next_credentials(payload):
    """Remove only pagination authentication before scanning the whole response."""
    if not isinstance(payload, dict) or not isinstance(payload.get("next_url"), str):
        return payload
    target = urlsplit(payload["next_url"])
    pairs = [(key, value) for key, value in parse_qsl(target.query, keep_blank_values=True)
             if key.lower() not in {"apikey", "token", "authorization"}]
    safe_url = urlunsplit((target.scheme, target.netloc, target.path, urlencode(pairs), target.fragment))
    return payload | {"next_url": safe_url}


def _next_request(next_url: str, url: str, original: dict) -> dict | None:
    if not next_url:
        return None
    target, first = urlsplit(next_url), urlsplit(url)
    require((target.scheme, target.netloc, target.path) == (first.scheme, first.netloc, first.path)
            and not target.fragment, "PAGINATION_SCOPE_REJECTED")
    pairs = [(k, v) for k, v in parse_qsl(target.query, keep_blank_values=True)
             if k.lower() not in {"apikey", "token", "authorization"}]
    require(len(dict(pairs)) == len(pairs), "PAGINATION_DUPLICATE_PARAMETER")
    query = dict(pairs)
    require(set(query) == set(original) | {"cursor"} and bool(query["cursor"]), "PAGINATION_MISSING_SCOPE")
    for key, value in original.items():
        expected = str(value).lower() if isinstance(value, bool) else str(value)
        require(query[key] == expected, "PAGINATION_PARAMETER_CHANGED")
    return original | {"cursor": query["cursor"]}


def _response_rows(payload: dict, probe: dict, kind: str, api_key: str) -> list[dict]:
    require("results" in payload, "RESPONSE_RESULTS_FIELD_MISSING")
    rows = payload["results"]
    require(isinstance(rows, list) and len(rows) <= 100, "RESPONSE_ROWS_INVALID")
    allowed = {"ticker", "underlying_ticker", "contract_type", "expiration_date", "strike_price", "exercise_style",
               "shares_per_contract", "correction", "additional_underlyings", "primary_exchange", "bid_price", "ask_price",
               "bid_size", "ask_size", "bid_exchange", "ask_exchange", "sip_timestamp", "participant_timestamp",
               "sequence_number", "conditions", "price", "size", "exchange", "id", "trf_timestamp"}
    first, last = pre2026(probe["start"]).value, pre2026(probe["end"]).value
    def safe(value):
        if isinstance(value, str):
            return re.sub(r"https?://\S+", "[URL_REDACTED]", value.replace(api_key, "[REDACTED]"))
        if isinstance(value, list):
            return [safe(item) for item in value]
        if isinstance(value, dict):
            return {k: safe(v) for k, v in value.items() if k.lower() not in {"apikey", "token", "authorization"}}
        return value
    output = []
    for row in rows:
        require(isinstance(row, dict), "RESPONSE_ROW_INVALID")
        if kind != "contracts":
            require(type(row.get("sip_timestamp")) is int, "RESPONSE_REQUIRED_TIMESTAMP_MISSING")
            require(first <= row["sip_timestamp"] <= last, "RESPONSE_RANGE_REJECTED")
            for key in ("participant_timestamp", "trf_timestamp"):
                if key in row and row[key] is not None:
                    require(type(row[key]) is int and first <= row[key] <= last, "RESPONSE_RANGE_REJECTED")
        else:
            require(row.get("underlying_ticker") == probe["underlying_symbol"] and row.get("contract_type") == "call",
                    "RESPONSE_CONTRACT_IDENTITY_REJECTED")
            require(30 <= (pd.Timestamp(row.get("expiration_date")).date() - pre2026(probe["start"]).date()).days <= 60,
                    "RESPONSE_CONTRACT_EXPIRY_REJECTED")
        output.append(safe({k: v for k, v in row.items() if k in allowed}))
    return output


def request_massive_history(*, api_key: str | None, probe: dict, url: str, params: dict,
                            state_path: Path, cache_root: Path, now=None, transport=None,
                            page_limit: int | None = None, sleep=None) -> dict:
    """One bounded qualification path; completed or uncertain attempts never resend.

    All rows remain UNQUALIFIED. No credential, current snapshot, account call,
    automatic retry or historical unit inference is part of this function.
    """
    _bound_probe(probe)
    require(page_limit is None or (type(page_limit) is int and 1 <= page_limit <= 12),
            "INVALID_QUALIFICATION_PAGE_LIMIT")
    expected = qualification_requests(probe, url.split("/v3/quotes/")[-1]) if "/v3/quotes/O:" in url else qualification_requests(probe)
    matches = [item for item in expected if item["url"] == url and item["params"] == params]
    require(len(matches) == 1, "REQUEST_NOT_FROZEN_QUALIFICATION_SCOPE")
    kind = matches[0]["kind"]
    validate_history_request(url, params, feed="PROVIDER_FIXED_FEED_SOURCE_UNVERIFIED",
                             start=probe["start"], end=probe["end"], probe=probe)
    current = now or time.time
    state_path, cache_root = Path(state_path), Path(cache_root)
    stamp = float(current())
    limits = {"provider_limit": 12, "total_limit": 1200, "cache_limit_bytes": 10737418240}
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {
        "research_identity": TEMPLATE, "started_epoch": stamp, "deadline_epoch": stamp + 4 * 3600,
        **limits, "attempts": [], "denied_paths": [], "explicit_denials": [], "authentication_stopped": False, "rate_limited": False}
    require(state.get("research_identity") == TEMPLATE and all(state.get(k) == v for k, v in limits.items())
            and state["deadline_epoch"] - state["started_epoch"] == 4 * 3600, "TRANSPORT_STATE_CHANGED")
    _write_json(state_path, state, api_key=api_key)
    result = {"status": "NOT_TESTABLE_NO_CREDENTIALS", "http_requests": 0, "cached_pages": 0, "rows": [],
              "row_count": 0, "page_complete": False, "authentication": "UNKNOWN", "entitlement": "UNKNOWN",
              "kind": kind, "fields_observed": [], "unit_status": "UNQUALIFIED", "evidence_grade": "UNQUALIFIED",
              "source_status": "UNQUALIFIED", "range_status": "NOT_OBSERVED", "http_status": None,
              "authentication_method": MASSIVE_AUTH_METHOD}
    cursor_params, seen = dict(params), set()
    while True:
        identity = {"probe_id": probe["decision_id"], "url": url, "params": cursor_params,
                    "authentication_method": MASSIVE_AUTH_METHOD}
        identity_bytes = json.dumps(identity, sort_keys=True).encode()
        _require_secret_safe(identity_bytes, api_key, "REQUEST_CONTAINS_CREDENTIAL_NOT_PERSISTED")
        digest = hashlib.sha256(identity_bytes).hexdigest()
        if digest in seen:
            result["status"] = "PAGINATION_LOOP_REJECTED"
            break
        seen.add(digest)
        prior = [item for item in state["attempts"] if item["request_sha256"] == digest]
        artifact = cache_root / (digest + ".json")
        if prior:
            require(len(prior) == 1, "DUPLICATE_TRANSPORT_ATTEMPT")
            if prior[0]["status"] != "COMPLETE":
                result["status"] = "UNCERTAIN_ATTEMPT_NO_RETRY"
                break
            require(artifact.exists(), "QUALIFIED_CACHE_IDENTITY_MISMATCH")
            cached_bytes = artifact.read_bytes()
            _require_secret_safe(cached_bytes, api_key, "CACHE_CONTAINS_CREDENTIAL_NOT_HASHED")
            require(hashlib.sha256(cached_bytes).hexdigest() == prior[0]["cache_sha256"], "QUALIFIED_CACHE_IDENTITY_MISMATCH")
            page = json.loads(cached_bytes)
            require(page["request"] == identity and page["evidence_grade"] == "UNQUALIFIED", "CACHE_SCOPE_CHANGED")
            result["cached_pages"] += 1
        else:
            stop = ("NOT_TESTABLE_NO_CREDENTIALS" if not api_key else "AUTHENTICATION_PATH_STOPPED" if state["authentication_stopped"]
                    else "RATE_LIMITED_PROVIDER_STOPPED" if state.get("rate_limited")
                    else "PERMISSION_PATH_STOPPED" if kind in state["denied_paths"] else "TIME_BUDGET_STOPPED" if current() + 35 >= state["deadline_epoch"]
                    else "REQUEST_BUDGET_STOPPED" if len(state["attempts"]) >= min(state["provider_limit"], state["total_limit"]) else None)
            if stop:
                result["status"] = stop
                if kind in state.get("explicit_denials", []):
                    result["entitlement"] = "DENIED_FOR_THIS_PATH"
                if stop == "AUTHENTICATION_PATH_STOPPED":
                    result["authentication"] = "REJECTED"
                break
            require(not artifact.exists(), "UNBOUND_CACHE_PRESERVED")
            used = sum(item.stat().st_size for item in cache_root.rglob("*") if item.is_file()) if cache_root.exists() else 0
            if used + 2 * 1024 * 1024 > state["cache_limit_bytes"]:
                result["status"] = "CACHE_BUDGET_STOPPED"
                break
            # R3 waits after completion, including failed requests. Restarts use
            # persisted completion times; old attempts get the full timeout bound.
            if state["attempts"]:
                last = state["attempts"][-1]
                finished = last.get("completed_epoch", last["at_epoch"] + 35)
                delay = max(0., finished + MIN_SECONDS_BETWEEN_REQUESTS - current())
                if current() + delay + 35 >= state["deadline_epoch"]:
                    result["status"] = "TIME_BUDGET_STOPPED"
                    break
                if delay:
                    (sleep or time.sleep)(delay)
                if current() + 35 >= state["deadline_epoch"]:
                    result["status"] = "TIME_BUDGET_STOPPED"
                    break
            attempt = {"request_sha256": digest, "kind": kind, "status": "PENDING_UNKNOWN", "at_epoch": float(current())}
            state["attempts"].append(attempt)
            _write_json(state_path, state, api_key=api_key)  # Persist before the HTTP attempt, including failures.
            result["http_requests"] += 1
            page = {"request": identity, "evidence_grade": "UNQUALIFIED", "rows": [], "next_params": None,
                    "status": "TRANSPORT_EXCEPTION", "http_status": None, "permission_explicit": False}
            try:
                status, payload = (transport or _history_get)(url, params=cursor_params,
                    api_key=api_key, headers={"Accept": "application/json"}, timeout=(5, 30), allow_redirects=False)
                page["http_status"] = status
                payload = _remove_next_credentials(payload)
                _require_secret_safe(payload, api_key, "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED")
                page["status"] = "HTTP_RESPONSE"
                if status == 403 and isinstance(payload, dict):
                    page["permission_explicit"] = any(payload.get(field) in {
                        "NOT_AUTHORIZED", "NOT_ENTITLED", "SUBSCRIPTION_REQUIRED", "PERMISSION_DENIED", "PLAN_NOT_SUPPORTED"}
                        for field in ("status", "error", "code") if isinstance(payload.get(field), str))
                if status == 200:
                    require(isinstance(payload, dict), "RESPONSE_BODY_INVALID")
                    page["rows"] = _response_rows(payload, probe, kind, api_key)
                    try:
                        page["next_params"] = _next_request(payload.get("next_url", ""), url, params)
                    except (ValueError, TypeError):
                        page["next_params"] = None
                        page["status"] = "PAGINATION_SCOPE_REJECTED"
                    _require_secret_safe(page["next_params"], api_key, "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED")
            except Exception as exc:
                # Never persist provider messages, exception strings or exception URLs.
                controlled = {"RESPONSE_SIZE_LIMIT", "RESPONSE_BODY_INVALID", "RESPONSE_ROWS_INVALID", "RESPONSE_ROW_INVALID",
                              "RESPONSE_RESULTS_FIELD_MISSING",
                              "RESPONSE_RANGE_REJECTED", "RESPONSE_REQUIRED_TIMESTAMP_MISSING",
                              "RESPONSE_CONTRACT_IDENTITY_REJECTED", "RESPONSE_CONTRACT_EXPIRY_REJECTED",
                              "RESPONSE_CONTAINS_CREDENTIAL_NOT_PERSISTED"}
                page["status"] = str(exc) if isinstance(exc, Invalid) and str(exc) in controlled else (
                    "RESPONSE_REJECTED" if page["http_status"] is not None else "TRANSPORT_EXCEPTION")
                page["rows"], page["next_params"] = [], None
            if page["http_status"] == 401:
                state["authentication_stopped"] = True
            if page["http_status"] == 403 and kind not in state["denied_paths"]:
                state["denied_paths"].append(kind)
            if page["permission_explicit"] and kind not in state.setdefault("explicit_denials", []):
                state["explicit_denials"].append(kind)
            if page["http_status"] == 429:
                state["rate_limited"] = True
            _write_json(artifact, page, api_key=api_key)
            attempt.update(status="COMPLETE", completed_epoch=float(current()), cache_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest())
            _write_json(state_path, state, api_key=api_key)
        status = page["http_status"]
        facts = classify_http(status, row_count=len(page["rows"]), permission_explicit=page.get("permission_explicit", False))
        result.update({key: facts[key] for key in ("authentication", "entitlement", "http_status")})
        result["rows"].extend(page["rows"])
        result["status"] = facts["response_state"] if page["status"] == "HTTP_RESPONSE" else page["status"]
        if page["status"] != "HTTP_RESPONSE" or status != 200:
            break
        result["range_status"] = "REQUEST_RANGE_VALIDATED_ROWS_CHECKED" if kind != "contracts" else "AS_OF_REQUESTED_VERSION_UNVERIFIED"
        if page["next_params"] is None:
            result["page_complete"] = True
            break
        if page_limit is not None and result["http_requests"] + result["cached_pages"] >= page_limit:
            result["status"] = "QUALIFICATION_PAGE_LIMIT"
            break
        cursor_params = page["next_params"]
    result["row_count"] = len(result["rows"])
    result["fields_observed"] = sorted({key for row in result["rows"] for key in row})
    result["provider_requests_consumed"] = len(state["attempts"])
    result["total_requests_consumed"] = len(state["attempts"])
    return result


def write_qualification(panel: pd.DataFrame, output: Path) -> dict:
    """Record this verified no-credential boundary; do not send guesses.

    New credentials do not authorize unplanned requests. If the environment
    changes, fail before writing a false no-credential receipt.
    """
    paths = resolve()
    out = Path(output).resolve()
    require(out.is_relative_to(paths.results_root / TEMPLATE / "overnight"), "OPTION_OUTPUT_OUTSIDE_OVERNIGHT")
    presence = credential_presence()
    require(not any(presence.values()), "CREDENTIAL_STATE_CHANGED_REQUIRES_BOUND_REQUEST_REVIEW")
    out.mkdir(parents=True, exist_ok=True)
    plan = {"research_identity": TEMPLATE, "role": "CURRENT_DATE_EXPLORATORY_APPENDIX",
            "frozen_at_utc": datetime.now(timezone.utc).isoformat(), "provider_probe_request_limit": 12,
            "total_incremental_request_limit": 1200, "selected": probe_plan(panel),
            "pilot_plan_status": "NOT_GENERATED_NO_PROVEN_PROVIDER_BBO_COVERAGE",
            "pilot_plan_count": 0, "economic_results_accessed_for_selection": False}
    plan_path = out / "fixed_probe_plan.json"
    if plan_path.exists():
        prior = json.loads(plan_path.read_text(encoding="utf-8"))
        require(prior["selected"] == plan["selected"], "FROZEN_PROBE_PLAN_CHANGED")
        plan = prior
    else:
        plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    facts = []
    for provider, endpoint, feed, limitation in [
        ("ALPACA", "/v2/options/contracts", "NOT_APPLICABLE_METADATA",
         "NO_CREDENTIALS; inactive filter documented; no historical as_of/version availability established"),
        ("ALPACA", "NO_VERIFIED_HISTORICAL_QUOTES_ENDPOINT", "opra",
         "NO_CREDENTIALS; official SDK documents historical bars/trades and latest quotes only; no guessed endpoint"),
        ("MASSIVE", "/v3/reference/options/contracts", "NOT_APPLICABLE_METADATA",
         "NO_CREDENTIALS; as_of and expired documented; their joint semantics and historical version completeness untested"),
        ("MASSIVE", "/v3/quotes/{optionsTicker}", "PROVIDER_FIXED_FEED_SOURCE_UNVERIFIED",
         "NO_CREDENTIALS; historical quotes documented; no feed selector; response source, units and historical access untested"),
        ("MOOMOO", "get_option_chain", "NOT_APPLICABLE",
         "REUSED_R1_NO_EXPIRED_CHAIN_SUPPORT; current snapshot paths forbidden; no repeated probe"),
    ]:
        facts.append({"provider": provider, "endpoint": endpoint, "feed": feed,
                      "status": "NOT_TESTABLE" if provider != "MOOMOO" else "UNSUITABLE_HISTORY_ENDPOINT",
                      **classify_http(None), "http_requests": 0, "sample_fields": "NOT_OBSERVED",
                      "requested_months": "2025-02;2025-05;2025-08", "remaining_limitations": limitation})
    pd.DataFrame(facts).to_csv(out / "option_qualification.csv", index=False)
    pd.DataFrame(columns=["decision_id", "provider", "contract_id", "entry_status", "exit_status",
                          "cash", "quantity", "net_wealth", "unresolved"]).to_csv(out / "actual_pairs.csv", index=False)
    summary = {"status": "COMPLETED_AVAILABLE_QUALIFICATION_BRANCHES", "credential_presence": presence,
               "economic_http_requests": 0, "probe_candidates": len(plan["selected"]), "contracts_verified": 0,
               "pilot_planned": 0, "fetched": 0, "entered": 0, "resolved": 0, "unresolved": 0,
               "economic_verdict": "NOT_IDENTIFIABLE", "account_executability": "NOT_RUN",
               "authentication": "UNKNOWN", "historical_bbo_entitlement": "UNKNOWN",
               "replay_limitations": ["NO_VERIFIED_BBO", "NO_0945_SYNCHRONOUS_UNDERLYING",
                                       "NO_PROVEN_OPTION_CLOCK_SIGNAL_AVAILABILITY", "NO_HISTORICAL_CONTRACT_SET"],
               "fixed_plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(), "official_sources": DOCS,
               "documentation_findings": {
                   "alpaca": "Historical data overview starts February 2024 and distinguishes modified indicative quotes from OPRA BBO. The guide says old data on all feeds can be accessible, while its overview describes OPRA subscription access. Neither resolves this account's permission. Current official SDK has historical bars/trades and latest quotes/snapshots/chain; a historical quotes endpoint was not established. Contract metadata has inactive status and expiry filters, but no documented historical as_of parameter on the checked page.",
                   "massive": "Historical contracts expose as_of and expired separately, correction, exercise_style and shares_per_contract. Their joint historical-version semantics require actual evidence. The historical quotes endpoint documents bid/ask, sizes, exchanges, sequence_number and SIP receipt nanoseconds; quote plan access is separate from contract metadata. Its size descriptions refer to share round lots, so option-contract size conversion remains unresolved. No account entitlement or response source was observed.",
               },
               "this_branch_exposure": {
                   "allowed_signal_input": "Pinned pre2026 continuation real_opportunities.csv decision fields",
                   "economic_api_payloads": 0,
                   "inadvertent_web_search_snippets": "Official-domain search included Alpaca community examples containing a 2026-01-30 option BBO and 2026-06-11 option bar; no page click or economic endpoint request; not used for selection; subsequent discovery restricted to exact documentation/official SDK URLs",
                   "project_2026_economic_data": "NOT_READ_BY_THIS_BRANCH",
                   "global_economic_read_count": "UNKNOWN",
               },
               "local_discovery": "No options BBO binding in original/continuation R1; this is not provider entitlement evidence",
               "resume": "No managed process or HTTP loop; do not retry absent credentials or guessed history endpoint"}
    (out / "qualification_summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary
