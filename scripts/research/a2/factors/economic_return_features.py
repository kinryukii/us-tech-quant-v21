"""Pure, explicit-event gross ex-date-accrual returns; no readers or simulators.

This is a research return convention, NOT spendable pay-date cash or certified
publication-PIT data. Raw closes and cash must have the same currency. One old
share becomes q new shares and D cash entitlement: (q * close + D) / prior - 1.
Moomoo split_ratio is OLD / NEW; A/B are never used to infer q or D.

Caller evidence is mandatory: classifier rows identify the source and pinned
SDK schema; a separate successful-query coverage table certifies dates with no
event rows. This module validates contracts, not the truth of those assertions.
It never excludes a security permanently after an unsupported event.
"""
from __future__ import annotations

import json
import numpy as np
import pandas as pd


CLASSIFIER_VERSION = "explicit_vendor_actions_v1"
ACTION_FIELDS = (
    "split_ratio", "split_base", "split_ert", "join_base", "join_ert",
    "per_cash_div", "special_dividend", "per_share_div_ratio", "bonus_base",
    "bonus_ert", "per_share_trans_ratio", "transfer_base", "transfer_ert",
    "allotment_ratio", "allotment_price", "allot_base", "allot_ert",
    "stk_spo_ratio", "stk_spo_price", "add_base", "add_ert",
    "spin_off_base", "spin_off_ert", "spin_off_ratio",
)
COMPLEX_FIELDS = ACTION_FIELDS[7:]
SOURCE_FIELDS = ("source_type", "source_reference", "source_fingerprint", "sdk_schema_fingerprint")
ADJUSTMENT_FIELDS = ("forward_adj_factorA", "forward_adj_factorB", "backward_adj_factorA", "backward_adj_factorB")
EVENT_COLUMNS = (
    "ticker", "ex_div_date", "event_supported", "event_status", "quantity_multiplier",
    "ordinary_cash", "special_cash", "cash_per_old_share", "cash_unit_basis",
    "classification_rule", "classifier_version", "event_fields_json", *SOURCE_FIELDS,
    "cash_unit_source_reference", "cash_unit_source_fingerprint",
)


def _true(value):
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _text(value):
    return "" if value is None or pd.isna(value) else str(value).strip()


def _dates(values, name, *, ordered=False):
    dates = pd.DatetimeIndex(pd.to_datetime(values, errors="raise"))
    if dates.hasnans or dates.tz is not None or not dates.equals(dates.normalize()):
        raise ValueError(f"{name}: normalized timezone-naive nonmissing dates required")
    if ordered and (dates.has_duplicates or not dates.is_monotonic_increasing):
        raise ValueError(f"{name}: unique increasing sessions required")
    return dates


def classify_vendor_events(events: pd.DataFrame) -> pd.DataFrame:
    """Classify full-schema SDK rows without prices or A/B economic inference.

    Required identity columns: ticker/ex_div_date. Required row evidence:
    SOURCE_FIELDS, action_fields_complete=True, identity_unchanged=True. Every
    ACTION_FIELDS column must exist, including absent-action columns as NaN.
    The complete schema assertion must be backed by its SDK and query evidence;
    do not manufacture it by reindexing an incomplete extraction. Cash rows also
    require cash_unit_basis='PER_OLD_SHARE_SAME_CURRENCY' and separate nonempty
    cash_unit_source_reference/fingerprint evidence; a US ticker is not proof.
    Optional company_act_flag
    is checked for unknown bits and missing active components when supplied.
    Unknown/complex/malformed actions become unsupported, never no-event.
    """
    if not {"ticker", "ex_div_date"}.issubset(events.columns):
        raise ValueError("events require ticker and ex_div_date")
    frame = events.copy()
    frame["ex_div_date"] = _dates(frame.ex_div_date, "event dates")
    if frame.ticker.isna().any() or frame.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("event ticker identity required")
    frame["ticker"] = frame.ticker.astype(str)
    if frame.duplicated(["ticker", "ex_div_date"]).any():
        raise ValueError("duplicate event day requires upstream explicit composition")
    schema_complete = set(ACTION_FIELDS).issubset(frame.columns)
    results = []
    for _, row in frame.iterrows():
        evidence = {name: _text(row.get(name)) for name in SOURCE_FIELDS}
        original = {name: (None if pd.isna(row.get(name, np.nan)) else row.get(name))
                    for name in (*ACTION_FIELDS, *ADJUSTMENT_FIELDS, "company_act_flag")}
        original = {key: (value.item() if isinstance(value, np.generic) else value)
                    for key, value in original.items()}
        out = {"ticker": row.ticker, "ex_div_date": row.ex_div_date,
               "event_supported": False, "event_status": "UNKNOWN_EVENT",
               "quantity_multiplier": np.nan, "ordinary_cash": np.nan,
               "special_cash": np.nan, "cash_per_old_share": np.nan,
               "cash_unit_basis": _text(row.get("cash_unit_basis")),
               "cash_unit_source_reference": _text(row.get("cash_unit_source_reference")),
               "cash_unit_source_fingerprint": _text(row.get("cash_unit_source_fingerprint")),
               "classification_rule": "UNSUPPORTED", "classifier_version": CLASSIFIER_VERSION,
               "event_fields_json": json.dumps(original, sort_keys=True, default=str), **evidence}
        status = None
        present = {key: row.get(key, np.nan) for key in ACTION_FIELDS if pd.notna(row.get(key, np.nan))}
        flag = row.get("company_act_flag", np.nan)
        if not schema_complete or not _true(row.get("action_fields_complete")) or not all(evidence.values()):
            status = "INCOMPLETE_ACTION_EVIDENCE"
        elif not _true(row.get("identity_unchanged")) or _true(row.get("unknown_identity")):
            status = "UNKNOWN_SECURITY_IDENTITY"
        elif _text(row.get("unsupported_action_reason")) or _true(row.get("unknown_action")):
            status = "UPSTREAM_UNSUPPORTED_ACTION"
        else:
            try:
                present = {key: float(value) for key, value in present.items()}
                if any(not np.isfinite(value) or value < 0 for value in present.values()):
                    status = "MALFORMED_ACTION_VALUE"
                if pd.notna(flag):
                    f = float(flag)
                    if not np.isfinite(f) or f < 0 or f != int(f) or int(f) & ~511:
                        status = "UNKNOWN_ACTION_FLAG"
                    else:
                        flag = int(f)
                        if flag & (4 | 8 | 16 | 32 | 256):
                            status = "UNSUPPORTED_COMPLEX_ACTION"
                        elif ((flag & 64 and "per_cash_div" not in present)
                              or (flag & 128 and "special_dividend" not in present)
                              or (flag & 3 and "split_ratio" not in present)):
                            status = "MISSING_FLAGGED_ACTION_VALUE"
                        elif (("per_cash_div" in present and not flag & 64)
                              or ("special_dividend" in present and not flag & 128)
                              or ("split_ratio" in present and not flag & 3)):
                            status = "CONFLICTING_ACTION_FLAG"
            except (TypeError, ValueError, OverflowError):
                status = "MALFORMED_ACTION_VALUE"
        if status is None and any(key in present for key in COMPLEX_FIELDS):
            status = "UNSUPPORTED_COMPLEX_ACTION"
        cash_action = "per_cash_div" in present or "special_dividend" in present
        split_action = any(key in present for key in ACTION_FIELDS[:5])
        q, ordinary, special = 1.0, 0.0, 0.0
        if status is None and cash_action and split_action:
            status = "UNSUPPORTED_MIXED_SPLIT_CASH"
        elif status is None and cash_action:
            if (out["cash_unit_basis"] != "PER_OLD_SHARE_SAME_CURRENCY"
                    or not out["cash_unit_source_reference"] or not out["cash_unit_source_fingerprint"]):
                status = "UNCONFIRMED_CASH_UNIT"
            else:
                ordinary = present.get("per_cash_div", 0.0)
                special = present.get("special_dividend", 0.0)
                out["classification_rule"] = "EXPLICIT_ORDINARY_PLUS_SPECIAL"
        elif status is None and split_action:
            ratio = present.get("split_ratio", np.nan)
            if not np.isfinite(ratio) or ratio <= 0:
                status = "INVALID_SPLIT_RATIO"
            elif (any(key in present for key in ("split_base", "split_ert"))
                  and any(key in present for key in ("join_base", "join_ert"))):
                status = "CONFLICTING_SPLIT_JOIN"
            elif pd.notna(flag) and int(flag) & 3 == 3:
                status = "CONFLICTING_SPLIT_JOIN"
            else:
                for base, ert in (("split_base", "split_ert"), ("join_base", "join_ert")):
                    if base in present or ert in present:
                        if base not in present or ert not in present or present[base] <= 0 or present[ert] <= 0:
                            status = "PARTIAL_SPLIT_COMPONENTS"
                        elif not np.isclose(present[base] / present[ert], ratio, rtol=1e-12, atol=0):
                            status = "CONFLICTING_SPLIT_RATIO"
                if (("split_base" in present or (pd.notna(flag) and int(flag) & 1)) and ratio >= 1
                        or ("join_base" in present or (pd.notna(flag) and int(flag) & 2)) and ratio <= 1):
                    status = "CONFLICTING_SPLIT_DIRECTION"
                q = 1.0 / ratio
                out["classification_rule"] = "EXPLICIT_RECIPROCAL_SPLIT_RATIO"
        elif status is None:
            # A/B can explain neither holdings nor whether an unknown action was
            # dropped by an old SDK. Even identity A/B does not prove no event.
            status = "UNKNOWN_EVENT"
            for name in ADJUSTMENT_FIELDS:
                value = row.get(name, np.nan)
                if pd.notna(value):
                    try:
                        if not np.isfinite(float(value)) or float(value) != (1.0 if name.endswith("A") else 0.0):
                            status = "UNEXPLAINED_ADJUSTMENT"
                    except (TypeError, ValueError):
                        status = "UNEXPLAINED_ADJUSTMENT"
        if status is None and (not np.isfinite(q) or q <= 0 or not np.isfinite(ordinary + special)):
            status = "NONFINITE_ECONOMIC_COMPONENT"
        if status is None:
            out.update(event_supported=True, event_status="SUPPORTED",
                       quantity_multiplier=q, ordinary_cash=ordinary,
                       special_cash=special, cash_per_old_share=ordinary + special)
        else:
            out["event_status"] = status
            out["classification_rule"] = "UNSUPPORTED"
        results.append(out)
    return pd.DataFrame(results, columns=EVENT_COLUMNS)


def build_accrual_returns(rawprices: pd.DataFrame, events: pd.DataFrame,
                          market_calendar: pd.DatetimeIndex, *,
                          event_coverage: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build strictly adjacent-session returns from classify_vendor_events output.

    event_coverage has one row per ticker: coverage_start, coverage_end,
    source_reference, source_fingerprint, complete=True. Complete means an accepted
    fixed vendor query snapshot covers the interval, not proof of all actual
    events or their historical publication time. Without it all returns are invalid,
    including dates without an event row. Active unsupported events invalidate
    only their own one-session return; no permanent ticker exclusion occurs.
    Optional rawprices.economic_security_id must come from correctly dated
    authoritative identity evidence, never fabricated from ticker or a delayed
    13F identifier activation. If supplied, equal nonempty IDs on both adjacent
    dates are required. Without it, valid only means vendor transport continuity,
    and identity_continuity_certified=False; that is not identity certification.
    Upstream must mask unresolved identity intervals and prevent factor windows
    combining different economic securities under one ticker, even if adjacent
    returns on either side separately resume.
    Returned close is unadjusted and is carried for downstream current-availability
    checks. Events outside the observed prefix never change prior results.
    """
    calendar = _dates(market_calendar, "market_calendar", ordered=True)
    if len(calendar) < 2:
        raise ValueError("market_calendar must contain at least two sessions")
    required = {"ticker", "trade_date", "close"}
    if not required.issubset(rawprices.columns) or rawprices.empty:
        raise ValueError("nonempty rawprices require ticker/trade_date/close")
    identity_supplied = "economic_security_id" in rawprices.columns
    frame = rawprices[["ticker", "trade_date", "close", *(["economic_security_id"] if identity_supplied else [])]].copy()
    frame["trade_date"] = _dates(frame.trade_date, "price dates")
    if not frame.trade_date.isin(calendar).all():
        raise ValueError("price date outside authoritative market calendar")
    if frame.ticker.isna().any() or frame.ticker.astype(str).str.strip().eq("").any():
        raise ValueError("price ticker identity required")
    frame["ticker"] = frame.ticker.astype(str)
    if frame.duplicated(["ticker", "trade_date"]).any():
        raise ValueError("duplicate price ticker/session")
    frame["close"] = pd.to_numeric(frame.close, errors="raise").astype(float)
    if not set(EVENT_COLUMNS).issubset(events.columns):
        raise ValueError("events must be classify_vendor_events output")
    classified = events.copy()
    classified["ex_div_date"] = _dates(classified.ex_div_date, "event dates")
    if classified.duplicated(["ticker", "ex_div_date"]).any():
        raise ValueError("duplicate classified event")
    if not classified.classifier_version.eq(CLASSIFIER_VERSION).all():
        raise ValueError("unrecognized event classifier version")
    end = frame.trade_date.max()
    active = classified.loc[classified.ex_div_date.between(calendar[0], end)]
    if not active.ex_div_date.isin(calendar).all():
        raise ValueError("active event date outside authoritative market calendar")
    coverage = {}
    if event_coverage is not None:
        cols = {"ticker", "coverage_start", "coverage_end", "source_reference", "source_fingerprint", "complete"}
        if not cols.issubset(event_coverage.columns) or event_coverage.ticker.duplicated().any():
            raise ValueError("unique ticker coverage evidence with required fields needed")
        for _, row in event_coverage.iterrows():
            start, stop = _dates([row.coverage_start, row.coverage_end], "coverage dates")
            if start > stop:
                raise ValueError("reversed event coverage")
            if _true(row.complete) and _text(row.source_reference) and _text(row.source_fingerprint):
                coverage[str(row.ticker)] = (start, stop, _text(row.source_reference), _text(row.source_fingerprint))
    sessions = calendar[calendar <= end]
    result = []
    for ticker, group in frame.groupby("ticker", sort=True):
        closes = group.set_index("trade_date").close.reindex(sessions)
        current_valid = np.isfinite(closes) & closes.gt(0)
        prior = closes.shift(1)
        prior_valid = np.isfinite(prior) & prior.gt(0)
        out = pd.DataFrame({"ticker": ticker, "trade_date": sessions, "close": closes.to_numpy(),
                            "prior_close": prior.to_numpy(), "current_close_available": current_valid.to_numpy(),
                            "prior_close_available": prior_valid.to_numpy()})
        out["identity_evidence_supplied"] = identity_supplied
        out["economic_security_id"] = ""
        out["prior_economic_security_id"] = ""
        out["identity_continuity_certified"] = False
        if identity_supplied:
            ids = group.set_index("trade_date").economic_security_id.reindex(sessions).map(_text)
            previous_ids = ids.shift(1).fillna("")
            out["economic_security_id"] = ids.to_numpy()
            out["prior_economic_security_id"] = previous_ids.to_numpy()
            out["identity_continuity_certified"] = (ids.ne("") & previous_ids.ne("") & ids.eq(previous_ids)).to_numpy()
        out["identity_status"] = np.where(out.identity_continuity_certified, "DATED_IDENTITY_CONTINUITY",
                                          "UNCONFIRMED_DATED_IDENTITY" if identity_supplied else "INHERITED_VENDOR_TRANSPORT_ONLY")
        out["event_present"] = False
        out["event_status"] = "NO_EVENT_WITH_COVERAGE"
        out["quantity_multiplier"] = 1.0
        out["ordinary_cash"] = 0.0
        out["special_cash"] = 0.0
        out["cash_per_old_share"] = 0.0
        for name in ("classification_rule", "event_fields_json", *SOURCE_FIELDS, "cash_unit_basis",
                     "cash_unit_source_reference", "cash_unit_source_fingerprint"):
            out[name] = ""
        out["classification_rule"] = "NO_EVENT_FROM_COMPLETE_QUERY"
        known = np.zeros(len(out), dtype=bool)
        out["coverage_source_reference"] = ""
        out["coverage_source_fingerprint"] = ""
        if ticker in coverage:
            start, stop, reference, fingerprint = coverage[ticker]
            known = np.asarray((sessions >= start) & (sessions <= stop))
            out.loc[known, "coverage_source_reference"] = reference
            out.loc[known, "coverage_source_fingerprint"] = fingerprint
        out["event_coverage_confirmed"] = known
        supported = np.ones(len(out), dtype=bool)
        date_position = {date: n for n, date in enumerate(sessions)}
        for _, event in active.loc[active.ticker.eq(ticker)].iterrows():
            n = date_position[event.ex_div_date]
            out.at[n, "event_present"] = True
            for name in ("event_status", "quantity_multiplier", "ordinary_cash", "special_cash",
                         "cash_per_old_share", "classification_rule", "event_fields_json",
                         *SOURCE_FIELDS, "cash_unit_basis", "cash_unit_source_reference", "cash_unit_source_fingerprint"):
                out.at[n, name] = event[name]
            supported[n] = _true(event.event_supported)
            if supported[n] and (not np.isfinite(event.quantity_multiplier) or event.quantity_multiplier <= 0
                                  or not np.isfinite(event.cash_per_old_share) or event.cash_per_old_share < 0):
                raise ValueError("malformed supported classified event")
        out["return_status"] = "VALID"
        unconfirmed_absence = ~known & ~out.event_present
        out.loc[unconfirmed_absence, "event_status"] = "EVENT_ABSENCE_UNCONFIRMED"
        out.loc[unconfirmed_absence, "classification_rule"] = "UNCONFIRMED_QUERY_COVERAGE"
        out.loc[unconfirmed_absence, ["quantity_multiplier", "ordinary_cash", "special_cash", "cash_per_old_share"]] = np.nan
        out.loc[~out.prior_close_available, "return_status"] = "MISSING_PRIOR_SESSION_CLOSE"
        out.loc[~out.current_close_available, "return_status"] = "MISSING_CURRENT_CLOSE"
        if identity_supplied:
            out.loc[~out.identity_continuity_certified, "return_status"] = "UNCONFIRMED_IDENTITY_CONTINUITY"
        out.loc[~supported, "return_status"] = "UNSUPPORTED_EVENT"
        out.loc[~known, "return_status"] = "EVENT_COVERAGE_UNCONFIRMED"
        out["return_valid"] = (out.current_close_available & out.prior_close_available & known & supported)
        if identity_supplied:
            out["return_valid"] &= out.identity_continuity_certified
        calculated = (out.quantity_multiplier * out.close + out.cash_per_old_share) / out.prior_close - 1.0
        if not np.isfinite(calculated.loc[out.return_valid]).all():
            raise ArithmeticError("nonfinite supported economic return")
        out["daily_gross_return"] = calculated.where(out.return_valid)
        result.append(out)
    return pd.concat(result, ignore_index=True).sort_values(["trade_date", "ticker"], kind="stable").reset_index(drop=True)
