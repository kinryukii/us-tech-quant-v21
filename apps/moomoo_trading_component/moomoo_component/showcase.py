"""One metadata owner for explicit display/paper rosters; never ranks on browse."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .strategy import ACTIVE_PAPER_STRATEGY_IDS, QUERYABLE_STRATEGY_IDS, APPLIED_STRATEGY_NAMES, timestamp

FIXED_IDS = ("RAW_A2", "HGB_DIAG_5")
_MAX_MANIFEST_BYTES = 65536
_MAX_SOURCE_BYTES = 1048576
_SHA = re.compile(r"[0-9a-f]{64}")
_FIELDS = {"schema_version", "kind", "revision_id", "created_at_utc", "effective_at_utc",
    "showcase_ids", "source_ref", "evaluation_window", "ranking_rule",
    "new_book_policy", "retired_book_policy", "broker_permission_granted"}


def _need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _reference(value):
    _need(isinstance(value, dict) and set(value) == {"path", "sha256"}
        and isinstance(value["path"], str) and bool(value["path"])
        and Path(value["path"]).is_absolute()
        and isinstance(value["sha256"], str) and _SHA.fullmatch(value["sha256"]),
        "SHOWCASE_ROSTER_REFERENCE_INVALID")
    return {"path": str(Path(value["path"]).resolve()), "sha256": value["sha256"]}


def validate_roster_manifest(value, *, now=None):
    """Validate metadata only. Selection metrics are never decoded by this owner."""
    _need(isinstance(value, dict) and set(value) == _FIELDS, "SHOWCASE_ROSTER_SCHEMA_INVALID")
    _need(type(value["schema_version"]) is int and value["schema_version"] == 1
        and value["kind"] == "SHOWCASE_PAPER_ROSTER_V1", "SHOWCASE_ROSTER_SCHEMA_INVALID")
    _need(isinstance(value["revision_id"], str)
        and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", value["revision_id"]), "SHOWCASE_ROSTER_REVISION_INVALID")
    created, effective = timestamp(value["created_at_utc"]), timestamp(value["effective_at_utc"])
    _need(created <= effective, "SHOWCASE_ROSTER_CLOCK_INVALID")
    if now is not None:
        _need(isinstance(now, datetime) and now.tzinfo is not None and now.utcoffset() is not None
            and effective <= now, "SHOWCASE_ROSTER_NOT_EFFECTIVE")
    ids = value["showcase_ids"]
    _need(isinstance(ids, list) and len(ids) == 5 and all(isinstance(sid, str) for sid in ids)
        and len(set(ids)) == 5 and ids[:2] == list(FIXED_IDS)
        and set(ids) <= set(QUERYABLE_STRATEGY_IDS), "SHOWCASE_ROSTER_FIVE_QUERYABLE_IDS_REQUIRED")
    _reference(value["source_ref"])
    window = value["evaluation_window"]
    _need(isinstance(window, dict) and set(window) == {"sample", "initialization_signal_date",
        "first_execution_date", "end", "selection_status"}
        and window["sample"] == "test_2026"
        and window["selection_status"] == "POST_EXPOSURE_DISPLAY_SELECTION",
        "SHOWCASE_ROSTER_EVALUATION_WINDOW_INVALID")
    days = []
    for key in ("initialization_signal_date", "first_execution_date", "end"):
        item = window[key]
        _need(isinstance(item, str) and date.fromisoformat(item).isoformat() == item
            and "2026-01-01" <= item < "2027-01-01", "SHOWCASE_ROSTER_EVALUATION_WINDOW_INVALID")
        days.append(item)
    _need(days[0] < days[1] <= days[2] and days[2] <= effective.date().isoformat(),
        "SHOWCASE_ROSTER_EVALUATION_WINDOW_INVALID")
    rule = value["ranking_rule"]
    _need(isinstance(rule, dict) and set(rule) == {"primary", "comparisons", "fixed_ids_excluded"}
        and rule["primary"] == "annualized_sharpe_desc"
        and rule["comparisons"] == ["total_return", "max_drawdown"]
        and rule["fixed_ids_excluded"] is True, "SHOWCASE_ROSTER_RANKING_RULE_INVALID")
    _need(value["new_book_policy"] == "INDEPENDENT_CASH_10000_FROM_ACCEPTANCE"
        and value["retired_book_policy"] == "PAUSE_PRESERVE_HISTORY"
        and value["broker_permission_granted"] is False, "SHOWCASE_ROSTER_PAPER_ONLY_REQUIRED")
    return deepcopy(value)


def _checked_file(ref, paths, limit, *, content=False):
    ref = _reference(ref)
    path = Path(ref["path"])
    root = (Path(paths.results_root) / "_maintenance").resolve()
    _need(path.is_relative_to(root), "SHOWCASE_ROSTER_RESULTS_PATH_REQUIRED")
    _need(path.is_file() and path.stat().st_size <= limit, "SHOWCASE_ROSTER_FILE_BOUND_INVALID")
    digest, chunks, count = hashlib.sha256(), [], 0
    with path.open("rb") as stream:
        while chunk := stream.read(min(65536, limit + 1 - count)):
            count += len(chunk)
            _need(count <= limit, "SHOWCASE_ROSTER_FILE_BOUND_INVALID")
            digest.update(chunk)
            if content:
                chunks.append(chunk)
    _need(digest.hexdigest() == ref["sha256"], "SHOWCASE_ROSTER_REFERENCE_CHANGED")
    return ref, b"".join(chunks) if content else None


def load_roster_reference(roster_ref, *, paths=None, now=None):
    """Verify bounded manifest/source bytes; this grants no model or broker readiness."""
    if paths is None:
        from scripts.common.storage_paths import resolve
        paths = resolve(Path(__file__).resolve().parents[3])
    ref, raw = _checked_file(roster_ref, paths, _MAX_MANIFEST_BYTES, content=True)

    def unique_pairs(pairs):
        result = {}
        for key, item in pairs:
            _need(key not in result, "SHOWCASE_ROSTER_DUPLICATE_JSON_KEY")
            result[key] = item
        return result

    manifest = validate_roster_manifest(json.loads(raw.decode("utf-8-sig"),
        object_pairs_hook=unique_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("SHOWCASE_ROSTER_NONFINITE_JSON"))),
        now=now or datetime.now(timezone.utc))
    _checked_file(manifest["source_ref"], paths, _MAX_SOURCE_BYTES)
    return {"roster_ref": ref, "manifest": manifest}


def validate_roster_binding(value):
    fields = {"schema_version", "revision_number", "roster_ref", "manifest", "accepted_at_utc",
        "previous_binding_sha256", "legacy_membership_binding_sha256", "legacy_active_strategy_ids", "retained_book_ids", "created_book_ids"}
    _need(isinstance(value, dict) and set(value) == fields and type(value["schema_version"]) is int
        and value["schema_version"] == 1 and type(value["revision_number"]) is int
        and value["revision_number"] > 0, "SHOWCASE_ROSTER_BINDING_INVALID")
    _reference(value["roster_ref"])
    accepted = timestamp(value["accepted_at_utc"])
    manifest = validate_roster_manifest(value["manifest"], now=accepted)
    _need(isinstance(value["legacy_membership_binding_sha256"], str)
        and _SHA.fullmatch(value["legacy_membership_binding_sha256"]), "SHOWCASE_ROSTER_BINDING_INVALID")
    previous = value["previous_binding_sha256"]
    _need(previous is None or isinstance(previous, str) and _SHA.fullmatch(previous),
        "SHOWCASE_ROSTER_BINDING_INVALID")
    for key in ("legacy_active_strategy_ids", "retained_book_ids", "created_book_ids"):
        ids = value[key]
        _need(isinstance(ids, list) and all(isinstance(sid, str) for sid in ids)
            and len(set(ids)) == len(ids) and set(ids) <= set(APPLIED_STRATEGY_NAMES),
            "SHOWCASE_ROSTER_BINDING_INVALID")
    _need(bool(value["legacy_active_strategy_ids"])
        and set(value["legacy_active_strategy_ids"]) <= set(value["retained_book_ids"])
        and set(manifest["showcase_ids"]) <= set(value["retained_book_ids"])
        and set(value["created_book_ids"]) <= set(manifest["showcase_ids"]),
        "SHOWCASE_ROSTER_BINDING_INVALID")
    return deepcopy(value)


def accepted_roster_projection(meta):
    """Pure projection of the original owner's accepted binding, not another registry."""
    _need(isinstance(meta, dict), "SHOWCASE_ROSTER_STATE_INVALID")
    binding = meta.get("showcase_roster_binding")
    if binding is None:
        _need(meta.get("roster_ref") is None, "SHOWCASE_ROSTER_ACCEPTED_BINDING_MISSING")
        ids = list(ACTIVE_PAPER_STRATEGY_IDS)
        revision, ref = None, None
    else:
        binding = validate_roster_binding(binding)
        ids = binding["manifest"]["showcase_ids"]
        ref = _reference(binding["roster_ref"])
        revision = binding["revision_number"]
        _need("roster_ref" not in meta or meta["roster_ref"] == ref, "SHOWCASE_ROSTER_STATE_REFERENCE_CHANGED")
    _need("showcase_ids" not in meta or meta["showcase_ids"] == ids, "SHOWCASE_ROSTER_STATE_IDS_CHANGED")
    return {"showcase_ids": list(ids), "roster_ref": ref, "roster_revision": revision,
        "inactive_queryable_ids": [sid for sid in QUERYABLE_STRATEGY_IDS if sid not in ids]}


def validate_state_projection(state):
    """Validate one bounded applied/view capture; API errors never fall back to v1."""
    _need(isinstance(state, dict) and not state.get("error")
        and isinstance(state.get("books"), (dict, list)), "SHOWCASE_ROSTER_STATE_UNAVAILABLE")
    result = accepted_roster_projection(state)
    _need("inactive_queryable_ids" not in state
        or state["inactive_queryable_ids"] == result["inactive_queryable_ids"],
        "SHOWCASE_ROSTER_STATE_IDS_CHANGED")
    return result
