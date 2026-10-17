"""Pure C R3 cutoff, identity qualification and canonical UID-return inputs.

The matched annual and monthly adapters share one record-proof implementation.
They read no files, targets, models or results and perform no fitting, moment
estimation, covariance or source acceptance. The caller owns source authority.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

import numpy as np
import pandas as pd

from scripts.research.a2.risk import joint_risk_estimators as risk
from scripts.research.a2.training.selector_challenge import TARGET
from scripts.research.a2.training.selector_risk_features import UNIT

ROLES = (
    "MONTHLY_FIXED_CORE_RIDGE", "MONTHLY_FIXED_CORE_HGB",
    "MONTHLY_COVERAGE_FLAG_ONLY_RIDGE", "MONTHLY_COVERAGE_FLAG_ONLY_HGB",
)
CORE = ("DIAG", "LW", "OAS", "PCA", "EWMA")
YEARS = (2022, 2023, 2024, 2025)
WINDOW = 63
BOUNDARY = pd.Timestamp("2026-01-01")
NO_CROSS_IDENTITY_STITCHING = "NO_CROSS_IDENTITY_STITCHING"
AUTHORIZED_CONTINUITY = "AUTHORIZED_CONTINUITY"
PROOF_FIELDS = (
    "identity_epoch", "available_at", "source_hash", "predecessor_uid",
    "predecessor_date", "return_unit",
)
EDGE_FIELDS = (
    "from_uid", "from_epoch", "from_source_hash", "to_uid", "to_epoch",
    "to_source_hash", "predecessor_date", "first_date", "available_at",
    "return_unit", "authorized", "authority_hash",
)


def _session(value):
    if value is None or pd.isna(value):
        raise ValueError("SESSION_MUST_BE_NONNULL_NORMALIZED_NAIVE")
    date = pd.Timestamp(value)
    if pd.isna(date) or date.tzinfo is not None or date != date.normalize():
        raise ValueError("SESSION_MUST_BE_NONNULL_NORMALIZED_NAIVE")
    return date


def _calendar(values):
    dates = pd.DatetimeIndex(values)
    if (dates.empty or dates.hasnans or dates.has_duplicates
            or dates.tz is not None or not dates.is_monotonic_increasing
            or not dates.equals(dates.normalize())):
        raise ValueError("ACCEPTED_SESSION_SEQUENCE_INVALID")
    return dates


def _instant(value):
    if value is None or pd.isna(value):
        return None
    try:
        stamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return stamp.tz_convert("UTC") if stamp.tzinfo is not None else None


def _finite(value):
    """Scalar numeric coercion only; invalid strings and missing values are absent."""
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError, OverflowError):
        return False


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _hash(value):
    return value.lower() if isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) else None


def _signature(row):
    return (row["security_uid"], _text(row.get("identity_epoch")),
            _hash(row.get("source_hash")), _text(row.get("return_unit")))


def _json_value(value):
    if value is None or (not isinstance(value, (list, dict, tuple)) and pd.isna(value)):
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return pd.Timestamp(value).isoformat()
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return "POSITIVE_INFINITY" if value > 0 else "NEGATIVE_INFINITY"
    if isinstance(value, np.generic):
        return value.item()
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def monthly_cutoffs(accepted_sessions, years=YEARS):
    """First accepted session of each registered month, from the existing clock."""
    dates = _calendar(accepted_sessions)
    if tuple(years) != YEARS:
        raise ValueError("MONTHLY_REGISTERED_YEARS_CHANGED")
    past = dates[dates.year.isin(YEARS) & (dates < BOUNDARY)]
    return tuple(past[~past.to_period("M").duplicated()])



def annual_cutoffs(years=YEARS):
    """Exact Jan 1 cutoffs; they are not moved to a trading session."""
    if tuple(years) != YEARS:
        raise ValueError("ANNUAL_REGISTERED_YEARS_CHANGED")
    return tuple(pd.Timestamp(f"{year}-01-01") for year in YEARS)


def _cutoff_clock(calendar, cutoff, cadence, decision_at):
    cut = _session(cutoff)
    if cadence == "MONTHLY":
        if cut not in monthly_cutoffs(calendar):
            raise ValueError("MONTHLY_CUTOFF_NOT_FIRST_REGISTERED_SESSION")
    elif cadence == "ANNUAL":
        if cut not in annual_cutoffs():
            raise ValueError("ANNUAL_CUTOFF_NOT_EXACT_REGISTERED_JAN1")
    else:
        raise ValueError("REGISTERED_CADENCE_REQUIRED")
    midnight = cut.tz_localize("America/New_York").tz_convert("UTC")
    limit = midnight if decision_at is None else _instant(decision_at)
    if limit is None or limit.tz_convert("America/New_York").tz_localize(None).normalize() != cut:
        raise ValueError("DECISION_AT_AWARE_ON_CUTOFF_DATE_REQUIRED")
    if cadence == "ANNUAL" and limit != midnight:
        raise ValueError("ANNUAL_DECISION_AT_MUST_BE_EXACT_JAN1_MIDNIGHT_NY")
    return cut, limit


def past_only_source_authority(row, *, cutoff, decision_at, source_authority):
    """Call the supplied shared authority only for already available past proof.

    No timestamp, source approval or identity link is invented here. A missing
    predicate or incomplete timing is false; the caller validates raw authority.
    """
    cut, limit = _session(cutoff), _instant(decision_at)
    if cut >= BOUNDARY:
        raise ValueError("SOURCE_AUTHORITY_CUTOFF_MUST_BE_REGISTERED_PRE2026")
    if limit is None or source_authority is None:
        return False
    if not callable(source_authority):
        raise ValueError("CALLABLE_SHARED_SOURCE_AUTHORITY_REQUIRED")
    try:
        day = _session(row.get("signal_date"))
    except (TypeError, ValueError):
        return False
    at = _instant(row.get("available_at"))
    if day >= cut or at is None or at >= limit:
        return False
    if "epoch_available_at" in row:
        epoch_at = _instant(row.get("epoch_available_at"))
        if epoch_at is None or epoch_at >= limit:
            return False
    return source_authority(row, cutoff=cut, decision_at=limit) is True


def assert_fixed_family(roles, *, seed=risk.SEED, cadence="MONTHLY",
                        window_sessions=WINDOW, min_observations=None,
                        target=TARGET, core_methods=CORE):
    """Validate the four declared slots; this grants no execution authority."""
    minimum = risk.COMMON["min_observations"]
    if min_observations is None:
        min_observations = minimum
    if tuple(roles) != ROLES or tuple(core_methods) != CORE:
        raise ValueError("FIXED_FOUR_ROLE_OR_CORE_FAMILY_CHANGED")
    if (isinstance(seed, bool) or seed != risk.SEED or cadence != "MONTHLY"
            or isinstance(window_sessions, bool) or window_sessions != WINDOW
            or isinstance(min_observations, bool) or min_observations != minimum
            or target != TARGET):
        raise ValueError("FIXED_SEED_CADENCE_WINDOW_MINIMUM_OR_TARGET_CHANGED")
    return {"roles": list(ROLES), "core_methods": list(CORE), "seed": seed,
            "cadence": cadence, "window_sessions": WINDOW,
            "min_observations": minimum, "target": TARGET,
            "fit_units": 0, "covariance_estimates": 0, "outcome_rows_read": 0}


def core_dependency_status(dependencies):
    """Check declared metadata slots without substitutes or model loading."""
    if not isinstance(dependencies, Mapping):
        raise ValueError("CORE_DEPENDENCY_METADATA_MAPPING_REQUIRED")
    missing = [name for name in CORE if dependencies.get(name) is not True]
    return {"status": "BLOCKED_DEPENDENCY" if missing else "CORE_DEPENDENCIES_PRESENT",
            "missing_core": missing, "core_methods": list(CORE),
            "fit_units": 0, "covariance_estimates": 0}


def mature_label_mask(signal_dates, label_end_dates, cutoff):
    """Strict maturity from date metadata only; no target values are accepted."""
    cut = _session(cutoff)
    if cut > BOUNDARY:
        raise ValueError("MATURITY_CUTOFF_AFTER_PRE2026")
    signal = pd.Series(pd.to_datetime(signal_dates, errors="raise"))
    mature = pd.Series(pd.to_datetime(label_end_dates, errors="raise"))
    if len(signal) != len(mature) or signal.dt.tz is not None or mature.dt.tz is not None:
        raise ValueError("MATURITY_DATE_SHAPE_OR_TIMEZONE")
    return signal.notna() & mature.notna() & signal.lt(cut) & mature.lt(cut) & mature.ge(signal)


def _universe(universe, cutoff, limit):
    if not {"security_uid", "ticker"}.issubset(universe):
        raise ValueError("FULL_UNIVERSE_UID_TICKER_KEYS_REQUIRED")
    allowed = ("security_uid", "ticker", "identity_epoch", "source_hash",
               "membership_date", "membership_available_at", "identity_available_at")
    out = universe.loc[:, [name for name in allowed if name in universe]].copy().reset_index(drop=True)
    if (out.empty or out.security_uid.map(_text).isna().any()
            or out.ticker.map(_text).isna().any()
            or out.security_uid.duplicated().any() or out.ticker.duplicated().any()):
        raise ValueError("FULL_UNIVERSE_KEYS_EMPTY_OR_AMBIGUOUS")
    if "membership_date" in out:
        dates = pd.to_datetime(out.membership_date, errors="raise")
        if dates.isna().any() or dates.dt.tz is not None or dates.gt(cutoff).any():
            raise ValueError("FUTURE_OR_INVALID_UNIVERSE_MEMBERSHIP")
    for name in ("membership_available_at", "identity_available_at"):
        if name in out:
            stamps = out[name].map(_instant)
            if stamps.map(lambda x: x is not None and x >= limit).any():
                raise ValueError("FUTURE_UNIVERSE_MEMBERSHIP_OR_IDENTITY")
    return out


def _past_records(history, calendar, cutoff, limit):
    if not {"signal_date", "security_uid"}.issubset(history):
        raise ValueError("HISTORY_DATE_UID_KEYS_REQUIRED")
    dates = pd.to_datetime(history.signal_date, errors="raise")
    if dates.isna().any() or dates.dt.tz is not None:
        raise ValueError("HISTORY_DATE_KEYS_INVALID")
    # Future date rows are isolated before numeric or identity fields are inspected.
    allowed = ("signal_date", "security_uid", "ticker", "ret_1d", *PROOF_FIELDS, "epoch_available_at")
    frame = history.loc[dates.lt(cutoff), [name for name in allowed if name in history]].copy()
    frame["signal_date"] = dates.loc[dates.lt(cutoff)]
    for name in ("available_at", "epoch_available_at"):
        if name in frame:
            stamps = frame[name].map(_instant)
            frame = frame.loc[~stamps.map(lambda x: x is not None and x >= limit)]
    if not frame.signal_date.isin(calendar).all() or frame.security_uid.map(_text).isna().any():
        raise ValueError("HISTORY_NONCALENDAR_OR_EMPTY_UID")
    if frame.duplicated(["signal_date", "security_uid"]).any():
        raise ValueError("AMBIGUOUS_PAST_UID_SESSION_RECORDS")
    frame = frame.sort_values(["signal_date", "security_uid"], kind="stable")
    return frame.to_dict("records")


def _complete_edges(edges, cutoff, limit, lookup, previous):
    if edges is None:
        return []
    if not set(EDGE_FIELDS).issubset(edges):
        return []
    valid = []
    for edge in edges.to_dict("records"):
        at = _instant(edge["available_at"])
        if (at is None or at >= limit or edge["authorized"] is not True
                or _hash(edge["authority_hash"]) is None or edge["return_unit"] != UNIT):
            continue
        try:
            first, prior = _session(edge["first_date"]), _session(edge["predecessor_date"])
        except (TypeError, ValueError):
            continue
        if first >= cutoff or previous.get(first) != prior:
            continue
        before = lookup.get((edge["from_uid"], prior))
        after = lookup.get((edge["to_uid"], first))
        if before is None or after is None:
            continue
        try:
            actual_pred = _session(after.get("predecessor_date"))
        except (TypeError, ValueError):
            continue
        old = (edge["from_uid"], _text(edge["from_epoch"]),
               _hash(edge["from_source_hash"]), UNIT)
        new = (edge["to_uid"], _text(edge["to_epoch"]),
               _hash(edge["to_source_hash"]), UNIT)
        if (old == new or None in old or None in new
                or _signature(before) != old or _signature(after) != new
                or after.get("predecessor_uid") != edge["from_uid"]
                or actual_pred != prior):
            continue
        b_at, a_at = _instant(before.get("available_at")), _instant(after.get("available_at"))
        if b_at is None or a_at is None or b_at > a_at or at > a_at:
            continue
        valid.append({**edge, "first_date": first, "predecessor_date": prior,
                      "available_at": at, "old": old, "new": new})
    return valid


def _qualify_history(history, accepted_sessions, cutoff, universe, *, cadence="MONTHLY",
                     decision_at=None, identity_policy=NO_CROSS_IDENTITY_STITCHING,
                     continuity_edges=None, source_authority=None):
    """Count the fixed 63 sessions by UID; preserve every caller supplied U_t key.

    ``potential_finite`` is a mechanical diagnostic after epoch reset, including
    rows with missing proof. ``qualified_finite`` counts only complete past
    availability/source/predecessor records. Neither accepts a source file.
    A default epoch/source transition quarantines its first crossing return.
    Explicit continuity needs a complete, authorized, already available edge.
    """
    calendar = _calendar(accepted_sessions)
    cut, limit = _cutoff_clock(calendar, cutoff, cadence, decision_at)
    if identity_policy not in (NO_CROSS_IDENTITY_STITCHING, AUTHORIZED_CONTINUITY):
        raise ValueError("REGISTERED_IDENTITY_POLICY_REQUIRED")
    if source_authority is not None and not callable(source_authority):
        raise ValueError("CALLABLE_SHARED_SOURCE_AUTHORITY_REQUIRED")
    keys = _universe(universe, cut, limit)
    dates = calendar[calendar < cut][-WINDOW:]
    minimum = risk.COMMON["min_observations"]
    fixed = {**assert_fixed_family(ROLES), "cadence": cadence,
             "identity_policy": identity_policy, "decision_at_exclusive": limit.isoformat(),
             "decision_at_supplied": decision_at is not None,
             "source_authority_supplied": source_authority is not None}
    panel = pd.DataFrame(np.nan, index=pd.DatetimeIndex(dates.to_numpy()),
                         columns=keys.security_uid.tolist())
    panel.index.name, panel.columns.name = "signal_date", "security_uid"
    if len(dates) != WINDOW:
        result = keys[["security_uid", "ticker"]].copy()
        result["status"] = "BLOCKED_WINDOW"
        result["potential_finite"] = result["qualified_finite"] = 0
        result["history_qualified_for_estimation"] = False
        result["legacy_ticker_finite_diagnostic"] = 0
        for name in ("reset_flag", "cold_start_flag", "authorized_continuity_flag", "unknown_proof_flag", "eligibility_upgraded"):
            result[name] = False
        result["quarantined_finite"] = result["unknown_proof_rows"] = 0
        metadata = {**fixed, "status": "BLOCKED_WINDOW", "source_accepted": False,
                        "calendar_sessions": len(dates), "cutoff_exclusive": cut.isoformat(),
                        "required_sessions": WINDOW, "full_U_t_preserved": True,
                        "coverage_count_performed": False,
                        "potential_finite_observations": 0, "qualified_finite_observations": 0,
                        "qualified_UIDs": 0, "UIDs": keys.security_uid.tolist(),
                        "status_counts": {"BLOCKED_WINDOW": len(keys)}}
        return result, metadata, panel
    records = _past_records(history, calendar, cut, limit)
    lookup = {(r["security_uid"], r["signal_date"]): r for r in records}
    previous = dict(zip(calendar[1:], calendar[:-1]))
    edges = (_complete_edges(continuity_edges, cut, limit, lookup, previous)
             if identity_policy == AUTHORIZED_CONTINUITY else [])
    result = []
    window = set(dates)
    relevant = {}
    by_uid, by_signature, by_ticker = {}, {}, {}
    for row in records:
        by_uid.setdefault(row["security_uid"], []).append(row)
        by_signature.setdefault(_signature(row), []).append(row)
        by_ticker.setdefault(row.get("ticker"), []).append(row)
    first_dates = {signature: rows[0]["signal_date"] for signature, rows in by_signature.items()}
    for key in keys.to_dict("records"):
        uid = key["security_uid"]
        own = by_uid.get(uid, [])
        selected, used_edges, reset, unknown = [], [], False, False
        if own:
            prior_identity = own[-1]
            relevant[(uid, prior_identity["signal_date"])] = {
                name: _json_value(prior_identity.get(name)) for name in
                ("signal_date", "security_uid", "ticker", "ret_1d", *PROOF_FIELDS, "epoch_available_at")}
            current = _signature(prior_identity)
            if (_text(key.get("identity_epoch")) is not None
                    and key["identity_epoch"] != current[1]):
                reset = True
                unknown = True
                own = []
            if _hash(key.get("source_hash")) is not None and key["source_hash"].lower() != current[2]:
                reset = True
                unknown = True
                own = []
            ticker_boundary = None
            if own:
                # A known other identity using the same ticker is negative
                # continuity evidence, never an authorization to borrow it.
                other = [r for r in by_ticker.get(key["ticker"], [])
                         if _signature(r) != current]
                if other:
                    latest_other = other[-1]
                    ticker_boundary = latest_other["signal_date"]
                    relevant[(latest_other["security_uid"], ticker_boundary)] = {
                        name: _json_value(latest_other.get(name)) for name in
                        ("signal_date", "security_uid", "ticker", "ret_1d", *PROOF_FIELDS, "epoch_available_at")}
                    if ticker_boundary >= own[-1]["signal_date"]:
                        reset, unknown, own = True, True, []
            if own:
                # A signature returning after another epoch is a new segment.
                # Reusing its older occurrences would itself stitch identities.
                start = 0
                if identity_policy == NO_CROSS_IDENTITY_STITCHING:
                    changed = [i for i, r in enumerate(own) if _signature(r) != current]
                    # A UID can return with its old epoch/source signature. Its
                    # intervening other UID is absent from ``own``; predecessor
                    # identity must therefore also delimit the newest segment.
                    for i, row in enumerate(own):
                        if _signature(row) != current:
                            continue
                        pred_uid = _text(row.get("predecessor_uid"))
                        try:
                            pred = lookup.get((pred_uid, _session(row.get("predecessor_date"))))
                        except (TypeError, ValueError):
                            pred = None
                        if ((pred_uid is not None and pred_uid != uid)
                                or (pred is not None and _signature(pred) != current)):
                            changed.append(i - 1)
                    start = max(changed) + 1 if changed else 0
                    if ticker_boundary is not None:
                        start = max(start, next(i for i, row in enumerate(own)
                                               if row["signal_date"] > ticker_boundary))
                current_start = own[start]["signal_date"]
                signatures = {current: cut}
                cursor = current
                while True:
                    matches = [e for e in edges if e["new"] == cursor]
                    if len(matches) != 1 or matches[0]["old"] in signatures:
                        break
                    edge = matches[0]
                    signatures[edge["old"]] = edge["first_date"]
                    used_edges.append(edge)
                    cursor = edge["old"]
                selected = [r for signature, end in signatures.items()
                            for r in by_signature[signature]
                            if r["signal_date"] < end and r["signal_date"] in window
                            and (identity_policy != NO_CROSS_IDENTITY_STITCHING
                                 or r["signal_date"] >= current_start)]
                selected.sort(key=lambda r: (r["signal_date"], r["security_uid"]))
                first = own[start] if identity_policy == NO_CROSS_IDENTITY_STITCHING else by_signature[current][0]
                try:
                    initial_pred = lookup.get((first.get("predecessor_uid"), _session(first.get("predecessor_date"))))
                except (TypeError, ValueError):
                    initial_pred = None
                declared_uid_boundary = _text(first.get("predecessor_uid")) not in (None, uid)
                reset = bool((ticker_boundary is not None or declared_uid_boundary or
                              (initial_pred is not None and _signature(initial_pred) != current))
                             and not used_edges)
        potential = qualified = quarantined = unknown_rows = 0
        for row in selected:
            signature = _signature(row)
            finite = _finite(row.get("ret_1d"))
            try:
                pred_date = _session(row.get("predecessor_date"))
            except (TypeError, ValueError):
                pred_date = None
            predecessor = lookup.get((row.get("predecessor_uid"), pred_date))
            before_sig = _signature(predecessor) if predecessor is not None else None
            first_of_signature = first_dates[signature] == row["signal_date"]
            crossing = before_sig is not None and before_sig != signature
            authorized = any(e["old"] == before_sig and e["new"] == signature
                             and e["first_date"] == row["signal_date"]
                             and e["predecessor_date"] == pred_date for e in used_edges)
            quarantine = (crossing or (first_of_signature and predecessor is None)) and not authorized
            if quarantine:
                reset = True
                quarantined += int(finite)
            potential += int(finite and not quarantine)
            at = _instant(row.get("available_at"))
            pred_at = _instant(predecessor.get("available_at")) if predecessor is not None else None
            complete = (None not in signature and signature[3] == UNIT
                        and at is not None and at < limit
                        and pred_date == previous.get(row["signal_date"])
                        and pred_at is not None and pred_at <= at
                        and (before_sig == signature or authorized))
            if complete and source_authority is not None:
                complete = (past_only_source_authority(row, cutoff=cut, decision_at=limit,
                                                      source_authority=source_authority)
                            and past_only_source_authority(predecessor, cutoff=cut, decision_at=limit,
                                                          source_authority=source_authority))
            if not complete:
                unknown_rows += 1
            qualified += int(finite and complete and not quarantine)
            if finite and complete and not quarantine:
                panel.loc[row["signal_date"], uid] = float(row["ret_1d"])
            for proof in (row, predecessor):
                if proof is not None:
                    relevant[(proof["security_uid"], proof["signal_date"])] = {
                        name: _json_value(proof.get(name)) for name in
                        ("signal_date", "security_uid", "ticker", "ret_1d", *PROOF_FIELDS, "epoch_available_at")}
        unknown = unknown or (bool(selected) and qualified == 0 and unknown_rows > 0 and not reset)
        if not own:
            status = "RESET_AND_QUARANTINE" if reset else "UNKNOWN" if unknown else "NO_HISTORY"
        elif not selected:
            status = "NO_HISTORY"
        elif unknown:
            status = "UNKNOWN"
        elif reset:
            status = "RESET_AND_QUARANTINE"
        elif used_edges:
            status = "AUTHORIZED_CONTINUITY"
        else:
            status = "FINITE_GE30" if qualified >= minimum else "FINITE_LT30"
        legacy = [r.get("ret_1d") for r in by_ticker.get(key["ticker"], []) if r["signal_date"] in window]
        legacy_count = sum(_finite(value) for value in legacy)
        result.append({"security_uid": uid, "ticker": key["ticker"], "status": status,
                       "legacy_ticker_finite_diagnostic": legacy_count,
                       "potential_finite": potential, "qualified_finite": qualified,
                       "history_qualified_for_estimation": qualified >= minimum,
                       "reset_flag": reset, "cold_start_flag": bool(reset and not own),
                       "authorized_continuity_flag": bool(used_edges),
                       "unknown_proof_flag": unknown or unknown_rows > 0,
                       "quarantined_finite": quarantined, "unknown_proof_rows": unknown_rows,
                       "eligibility_upgraded": False})
    output = pd.DataFrame(result)
    binding = {"cutoff": cut.isoformat(), "sessions": [d.isoformat() for d in dates],
               "universe": [{name: _json_value(k.get(name)) for name in
                             ("security_uid", "ticker", "identity_epoch", "source_hash", "membership_date",
                              "membership_available_at", "identity_available_at")} for k in keys.to_dict("records")],
               "records": [relevant[key] for key in sorted(relevant, key=lambda key: (key[1], key[0]))],
               "qualification": output.to_dict("records"),
               "continuity_edges": [{name: _json_value(e[name]) for name in EDGE_FIELDS}
                                    for e in edges], "spec": fixed, "return_unit": UNIT}
    metadata = {**fixed, "status": "MECHANICAL_QUALIFICATION_ONLY", "source_accepted": False,
                "qualification_scope": "ROW_RECORD_PROOF_ONLY_NOT_SOURCE_AUTHORITY",
                "coverage_count_performed": True,
                "cutoff_exclusive": cut.isoformat(), "calendar_sessions": WINDOW,
                "dates": binding["sessions"], "return_unit": UNIT,
                "potential_finite_observations": int(output.potential_finite.sum()),
                "qualified_finite_observations": int(output.qualified_finite.sum()),
                "qualified_UIDs": int(output.history_qualified_for_estimation.sum()),
                "status_counts": {str(k): int(v) for k, v in output.status.value_counts().items()},
                "full_U_t_preserved": True, "UIDs": keys.security_uid.tolist(),
                "qualification_sha256": _digest(binding)}
    return output, metadata, panel


def qualify_history(history, accepted_sessions, cutoff, universe, *, cadence="MONTHLY",
                    decision_at=None, identity_policy=NO_CROSS_IDENTITY_STITCHING,
                    continuity_edges=None, source_authority=None):
    """Shared annual/monthly mechanical qualification; no source acceptance.

    New callers use explicit ``decision_at``. The annual instant is exactly
    Jan 1 midnight New York; monthly availability may precede that first session's
    explicit decision instant while return dates remain strictly before cutoff.
    """
    output, metadata, _ = _qualify_history(
        history, accepted_sessions, cutoff, universe, cadence=cadence,
        decision_at=decision_at, identity_policy=identity_policy,
        continuity_edges=continuity_edges, source_authority=source_authority)
    return output, metadata


def qualify_monthly_history(history, accepted_sessions, cutoff, universe, *, continuity_edges=None,
                            decision_at=None, identity_policy=NO_CROSS_IDENTITY_STITCHING,
                            source_authority=None):
    """Mechanical monthly API; explicit legacy continuity grants no R3 authority."""
    return qualify_history(history, accepted_sessions, cutoff, universe, cadence="MONTHLY",
                           decision_at=decision_at, identity_policy=identity_policy,
                           continuity_edges=continuity_edges, source_authority=source_authority)


def qualify_annual_history(history, accepted_sessions, cutoff, universe, *, decision_at=None,
                           source_authority=None):
    """Matched exact Jan 1 adapter under the fixed no-stitching policy."""
    return qualify_history(history, accepted_sessions, cutoff, universe, cadence="ANNUAL",
                           decision_at=decision_at, source_authority=source_authority)


def canonical_uid_return_panel(history, accepted_sessions, cutoff, universe, *, cadence,
                               decision_at, source_authority=None):
    """Mask unproved history and retain full U_t for existing canonical estimators.

    This is input adaptation only. Neither the estimator nor its unknown/prior
    and full-pool projection implementation is duplicated. A missing shared raw
    authority predicate masks all cells; it never promotes record proof to source
    approval. ``coverage`` reports the existing >=30 rule without fitting it.

    ``universe`` must be the caller-certified cutoff-known fit UID roster. An
    annual Jan 1 call must not obtain it from the future first-session roster.
    Supplied membership/identity clocks are checked, but missing roster authority
    cannot be reconstructed here. Later daily entrants belong to the existing
    canonical full-pool projection with unknown/prior, never to an earlier fit.
    """
    if decision_at is None:
        raise ValueError("EXPLICIT_PANEL_DECISION_AT_REQUIRED")
    supplied = source_authority is not None
    authority = source_authority if supplied else lambda row, **clock: False
    coverage, metadata, panel = _qualify_history(
        history, accepted_sessions, cutoff, universe, cadence=cadence,
        decision_at=decision_at, identity_policy=NO_CROSS_IDENTITY_STITCHING,
        source_authority=authority)
    coverage = coverage.copy()
    coverage["risk_unknown_fallback"] = ~coverage.history_qualified_for_estimation
    coverage["risk_coverage_flag"] = coverage.risk_unknown_fallback
    digest = hashlib.sha256(
        pd.util.hash_pandas_object(panel, index=True).to_numpy(np.uint64).tobytes()
    ).hexdigest()
    status = (metadata["status"] if metadata["status"] == "BLOCKED_WINDOW"
              else "UID_PANEL_QUALIFIED" if supplied else "BLOCKED_SOURCE_AUTHORITY")
    metadata = {**metadata, "source_authority_supplied": supplied, "status": status,
                "candidate_roles_scope": "R3_SCIENTIFIC_ROLES_ONLY_NOT_ANNUAL_CANDIDATES",
                "cadence_scope": "INPUT_ADAPTER_CLOCK_ONLY",
                "fit_pool_authority": "CALLER_SUPPLIED_CUTOFF_KNOWN_UID_ROSTER_REQUIRED",
                "new_daily_entrants": "canonical project(bundle, daily full UID pool) owns prior fallback",
                "returns_sha256": digest, "assets": panel.columns.tolist(),
                "return_horizon_sessions": 1, "target": TARGET,
                "unproved_returns": "NaN; canonical estimator owns unknown independent prior fallback",
                "estimator_owner": "scripts.research.a2.risk.joint_risk_estimators",
                "projection_owner": "scripts.research.a2.training.selector_risk_features.project"}
    return panel, coverage, metadata
