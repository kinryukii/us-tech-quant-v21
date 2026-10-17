"""Bounded read-only projections of existing component plans and paper books.

The component remains the only inference/execution owner. Research history is
not manufactured from these forward account observations.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date
import http.client
import json
import math
from time import monotonic

import streamlit as st

from apps.moomoo_trading_component.moomoo_component.strategy import (
    ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS, APPLIED_STRATEGY_NAMES,
)

_MAX_BYTES = 4 * 1024 * 1024
_CONNECTION_TIMEOUT_SECONDS = 10
_TOTAL_TIMEOUT_SECONDS = 15
_READ_CHUNK_BYTES = 64 * 1024
_CURRENT_IDS = ACTIVE_PAPER_STRATEGY_IDS[2:]


@st.cache_data(ttl=15, max_entries=1, show_spinner=False)
def load_state():
    """The original bounded financial display capture; read only when needed."""
    return _read_projection("/api/applied/view", _MAX_BYTES)


@st.cache_data(ttl=15, max_entries=1, show_spinner=False)
def load_roster():
    """The mechanism gallery needs membership metadata, not account history."""
    return _read_projection("/api/applied/showcase-roster", 64 * 1024)


def _read_projection(endpoint, max_bytes):
    """One fixed loopback transport owner with a per-projection body cap."""
    if endpoint not in ("/api/applied/view", "/api/applied/showcase-roster"):
        raise ValueError("APPLIED_ACCOUNT_ENDPOINT_NOT_ALLOWED")
    deadline = monotonic() + _TOTAL_TIMEOUT_SECONDS
    connection = http.client.HTTPConnection("127.0.0.1", 8766, timeout=_CONNECTION_TIMEOUT_SECONDS)

    def remaining_timeout():
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("APPLIED_ACCOUNT_TOTAL_TIMEOUT")
        if connection.sock is not None:
            connection.sock.settimeout(remaining)

    try:
        connection.request("GET", endpoint, headers={"Accept": "application/json"})
        remaining_timeout()
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError("APPLIED_ACCOUNT_HTTP_STATUS")
        raw = bytearray()
        while True:
            remaining_timeout()
            chunk = response.read1(min(_READ_CHUNK_BYTES, max_bytes + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > max_bytes:
                raise ValueError("APPLIED_ACCOUNT_RESPONSE_LIMIT")
        value = json.loads(raw)
        if not isinstance(value, dict) or value.get("ok") is not True or not isinstance(value.get("data"), dict):
            raise ValueError("APPLIED_ACCOUNT_RESPONSE_SCHEMA")
        state = value["data"]
        if not isinstance(state.get("books"), (dict, list)):
            raise ValueError("APPLIED_ACCOUNT_BOOK_SCHEMA")
        return state
    except (OSError, ValueError, http.client.HTTPException, UnicodeError) as exc:
        return {"books": {}, "error": str(exc)}
    finally:
        connection.close()


def books(state):
    """Retired books remain queryable; active capture takes precedence by ID."""
    def indexed(value):
        if not isinstance(value, (dict, list, tuple)):
            return {}
        return {book["strategy_id"]: book for book in (value.values() if isinstance(value, dict) else value)
                if isinstance(book, dict) and book.get("strategy_id") in QUERYABLE_STRATEGY_IDS}
    legacy = state.get("legacy_history") or {}
    return {**indexed(legacy.get("books", {}) if isinstance(legacy, dict) else {}),
            **indexed(state.get("books", {}))}


def observation_dates(state):
    """Only explicitly recorded signal dates; account mark dates are separate."""
    days = set()
    for book in books(state).values():
        value = (book.get("plan") or {}).get("signal_date")
        try:
            if isinstance(value, str) and date.fromisoformat(value).isoformat() == value and "2026-01-01" <= value < "2027-01-01":
                days.add(value)
        except ValueError:
            pass
    return tuple(sorted(days))


def _empty(strategy_id, cutoff, reason):
    return {"strategy_id": strategy_id, "label": APPLIED_STRATEGY_NAMES[strategy_id],
        "status": "UNAVAILABLE", "requested_cutoff": cutoff, "error": reason,
        "history": {"status": "UNAVAILABLE", "daily": [], "summary": None,
            "start": None, "end": None, "reason": "No bound accepted research replay is available."},
        "target": {"kind": "UNAVAILABLE", "status": "UNAVAILABLE", "rows": [],
            "signal_date": None, "execution_date": None, "target_cash_weight": None,
            "reason": reason, "account_basis": "CURRENT_PAPER_ACCOUNT"},
        "model_identity": {}}


def current_view(state, strategy_id, cutoff):
    """An exact-date verified plan remains a target, even after paper fills."""
    result = _empty(strategy_id, cutoff, state.get("error") or "No verified account plan on this observation date.")
    book = books(state).get(strategy_id)
    if book is None:
        return result
    plan = book.get("plan") or {}
    if plan.get("signal_date", plan.get("source_date")) != cutoff or plan.get("strategy_id") != strategy_id:
        return result
    rows = plan.get("rows")
    cash = plan.get("target_cash_weight")
    finite = lambda value: type(value) in (int, float) and math.isfinite(value) and value >= 0
    if (plan.get("status") != "READY" or plan.get("model_fit_calls") != 0
            or plan.get("broker_action_allowed") is not False or not isinstance(rows, list)
            or not finite(cash) or any(not isinstance(row, dict) or not row.get("ticker")
                or not finite(row.get("target_weight")) for row in rows)
            or len({row["ticker"] for row in rows}) != len(rows)
            or abs(sum(row["target_weight"] for row in rows) + cash - 1) > 1e-7):
        result.update(status="BLOCKED", error="APPLIED_ACCOUNT_PLAN_VERIFICATION_FAILED")
        result["target"].update(status="BLOCKED", reason=result["error"])
        return result
    target = {**deepcopy(plan), "kind": "CURRENT_ACCOUNT_TARGET", "execution_status": "TARGET_ONLY",
        "account_basis": plan.get("account_basis", "CURRENT_PAPER_ACCOUNT"),
        "rows": [{**deepcopy(row), "weight_before": row.get("weight_before"),
            "action": row.get("action")} for row in rows], "reason": ""}
    result.update(status="AVAILABLE", error=None, target=target,
        model_identity=deepcopy(plan.get("model_identity") or {key: plan[key] for key in (
            "model_id", "model_ref", "model_sha256", "fit_cutoff_exclusive", "policy_id",
            "requested_gross", "previous_gross", "signal_date") if key in plan}),
        source_refs=deepcopy(plan.get("source_refs", {})),
        current_account={key: deepcopy(book.get(key)) for key in (
            "account_id", "cash", "equity", "positions", "status", "valuation", "nav_history")})
    return result


def views(state, cutoff):
    return {sid: current_view(state, sid, cutoff) for sid in _CURRENT_IDS}


def rankings(state, cutoff, *, strategy_ids=None):
    ids = ACTIVE_PAPER_STRATEGY_IDS if strategy_ids is None else tuple(strategy_ids)
    if len(set(ids)) != len(ids) or not set(ids) <= set(QUERYABLE_STRATEGY_IDS):
        raise ValueError("UNKNOWN_ACCOUNT_RANKING_STRATEGY")
    result = {}
    for sid in ids:
        view = current_view(state, sid, cutoff)
        target = view["target"]
        rows = [{**deepcopy(row), "model_rank": row.get("model_rank"), "score": row.get("score"),
            "selected": row["target_weight"] > 0, "target_kind": target["kind"],
            "weight_date": target["signal_date"]} for row in target["rows"]]
        result[sid] = {"status": view["status"], "actual_signal_date": target["signal_date"],
            "weight_date": target["signal_date"], "target_kind": target["kind"],
            "scope": "RECORDED_FROZEN_MODEL_INPUTS", "rows": rows}
    return result


def showcase_projection(state=None):
    """Consume the component's accepted roster; browsing never selects or migrates."""
    from apps.moomoo_trading_component.moomoo_component.showcase import validate_state_projection
    return validate_state_projection(load_roster() if state is None else state)
