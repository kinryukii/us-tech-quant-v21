#!/usr/bin/env python
"""Shared broad-date gate helpers for V21 daily-chain research stages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GATE_PATH = (
    ROOT
    / "outputs/v21/V21.192_CANONICAL_DATE_COVERAGE_GATE_AND_BROAD_LATEST_DATE_RESOLUTION/latest_broad_date_gate.json"
)


class BroadDateGateError(RuntimeError):
    """Raised when the broad-date gate is missing or invalid."""


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    return bool(value)


def _normalize_gate(raw: dict[str, Any], source_path: Path) -> dict[str, Any]:
    blocked = raw.get("blocked_newer_dates")
    if blocked is None:
        blocked = raw.get("narrow_tail_dates_must_not_be_used_for_abcde", [])
    if isinstance(blocked, str):
        blocked = [blocked]
    gate = {
        "raw_canonical_max_date": str(raw.get("raw_canonical_max_date", "")),
        "raw_canonical_max_date_symbol_count": int(raw.get("raw_canonical_max_date_symbol_count", 0) or 0),
        "raw_canonical_max_date_broad_eligible": _as_bool(raw.get("raw_canonical_max_date_broad_eligible", False)),
        "broad_price_latest_date": str(raw.get("broad_price_latest_date", "")),
        "feature_latest_date_technical": str(raw.get("feature_latest_date_technical", "")),
        "feature_latest_date_momentum": str(raw.get("feature_latest_date_momentum", "")),
        "abcd_honest_latest_date": str(raw.get("abcd_honest_latest_date", "")),
        "narrow_tail_detected": _as_bool(raw.get("narrow_tail_detected", bool(blocked))),
        "narrow_tail_row_count": int(raw.get("narrow_tail_row_count", len(blocked)) or 0),
        "blocked_newer_dates": sorted({str(item) for item in blocked if str(item)}),
        "gate_source_path": str(source_path),
        "gate_loaded": True,
    }
    return gate


def load_latest_broad_date_gate(gate_path: str | Path | None = None) -> dict[str, Any]:
    """Load and normalize the latest broad-date gate artifact."""
    path = Path(gate_path) if gate_path else DEFAULT_GATE_PATH
    if not path.is_file():
        raise BroadDateGateError(f"Broad-date gate missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    gate = _normalize_gate(payload, path)
    required = ["broad_price_latest_date", "abcd_honest_latest_date"]
    missing = [key for key in required if not gate.get(key)]
    if missing:
        raise BroadDateGateError(f"Broad-date gate missing required fields: {', '.join(missing)}")
    return gate


def resolve_honest_latest_date(gate: dict[str, Any] | None = None) -> str:
    """Return the ABCD honest latest date that ABCDE stages must target."""
    gate = gate or load_latest_broad_date_gate()
    return str(gate["abcd_honest_latest_date"])


def classify_requested_date(requested_date: str, gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify whether a requested ABCDE date is allowed by the broad-date gate."""
    gate = gate or load_latest_broad_date_gate()
    requested = str(requested_date)
    honest = str(gate["abcd_honest_latest_date"])
    broad = str(gate["broad_price_latest_date"])
    raw = str(gate["raw_canonical_max_date"])
    blocked = set(gate.get("blocked_newer_dates", []))
    if requested in blocked or (requested > honest and requested > broad):
        status = "NARROW_TAIL_BLOCKED" if requested <= raw else "TARGET_DATE_NOT_BROAD_ELIGIBLE"
        allowed = False
        reason = "Requested date is newer than abcd_honest_latest_date and is not broad feature eligible."
    elif requested == honest:
        status = "ALLOWED_HONEST_LATEST_DATE"
        allowed = True
        reason = "Requested date equals abcd_honest_latest_date."
    elif requested < honest:
        status = "ALLOWED_HISTORICAL_BROAD_DATE"
        allowed = True
        reason = "Requested date is not newer than abcd_honest_latest_date."
    else:
        status = "TARGET_DATE_NOT_BROAD_ELIGIBLE"
        allowed = False
        reason = "Requested date is not proven broad eligible by latest_broad_date_gate.json."
    return {
        **gate,
        "requested_date": requested,
        "classification": status,
        "allowed": allowed,
        "reason": reason,
        "final_status_if_blocked": "FAIL_OR_BLOCKED_TARGET_DATE_NOT_BROAD_ELIGIBLE",
        "final_decision_if_blocked": "USE_ABCD_HONEST_LATEST_DATE_OR_IMPORT_BROAD_DAILY_BARS",
    }


def assert_target_date_is_broad_eligible(requested_date: str, gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return classification or raise if requested date is not allowed."""
    result = classify_requested_date(requested_date, gate)
    if not result["allowed"]:
        raise BroadDateGateError(f"{result['classification']}: {requested_date} > {result['abcd_honest_latest_date']}")
    return result


def build_blocked_newer_dates_audit(gate: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build CSV-friendly rows for narrow-tail dates that ABCDE must not use."""
    gate = gate or load_latest_broad_date_gate()
    return [
        {
            "blocked_date": date,
            "classification": "NARROW_TAIL_BLOCKED",
            "abcd_honest_latest_date": gate["abcd_honest_latest_date"],
            "broad_price_latest_date": gate["broad_price_latest_date"],
            "reason": "Narrow tail date is not broad feature eligible.",
        }
        for date in gate.get("blocked_newer_dates", [])
    ]


def emit_broad_date_gate_snapshot(output_path: str | Path, gate: dict[str, Any] | None = None) -> dict[str, Any]:
    """Write a normalized broad-date gate snapshot without mutating canonical data."""
    gate = gate or load_latest_broad_date_gate()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(gate, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return gate
